import json
import logging
import os

import boto3

# Initialize AWS clients
route53 = boto3.client("route53")
autoscaling = boto3.client("autoscaling")
ec2 = boto3.client("ec2")

# Environment variables
TTL = int(os.getenv("TTL", 60))  # Default TTL if not set
HOSTED_ZONE_ID = os.getenv("ZONE_ID", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "ERROR").upper()

# Configure logging
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        message = json.loads(event["Records"][0]["Sns"]["Message"])
        logger.info(f"Parsed SNS message: {message}")

        lifecycle_action_token = message["LifecycleActionToken"]
        lifecycle_hook_name = message["LifecycleHookName"]
        autoscaling_group_name = message["AutoScalingGroupName"]
        instance_id = message["EC2InstanceId"]
        lifecycle_transition = message["LifecycleTransition"]

        logger.info(f"Instance ID: {instance_id}, Transition: {lifecycle_transition}")

        # Retrieve the instance tags to get the "Host" tag
        hostname = get_instance_hostname(instance_id)
        if not hostname:
            logger.error(f"Hostname tag not found for instance: {instance_id}")
            return

        # Check lifecycle transition to determine whether to create or delete the DNS record
        if lifecycle_transition == "autoscaling:EC2_INSTANCE_LAUNCHING":
            dns_action = "CREATE"
            handle_dns_action(instance_id, hostname, dns_action)
        elif lifecycle_transition == "autoscaling:EC2_INSTANCE_TERMINATING":
            dns_action = "DELETE"
            handle_dns_action(instance_id, hostname, dns_action)
        else:
            logger.warning(f"Unhandled lifecycle transition: {lifecycle_transition}")
            complete_lifecycle_action(
                autoscaling_group_name,
                lifecycle_hook_name,
                lifecycle_action_token,
                "CONTINUE",
            )
            return

        # Complete the lifecycle action
        complete_lifecycle_action(
            autoscaling_group_name,
            lifecycle_hook_name,
            lifecycle_action_token,
            "CONTINUE",
        )

    except Exception as e:
        logger.error(f"Error processing event: {str(e)}", exc_info=True)
        raise


def get_instance_hostname(instance_id):
    """
    Retrieve the 'Host' tag value for the given EC2 instance.
    """
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response["Reservations"][0]["Instances"][0]

        # Find the 'Host' tag
        for tag in instance.get("Tags", []):
            if tag["Key"] == "Host":
                return tag["Value"]

        # If no 'Host' tag is found, log an error and return None
        logger.error(f"Host tag not found for instance: {instance_id}")
        return None

    except Exception as e:
        logger.error(
            f"Error retrieving instance tags for {instance_id}: {str(e)}", exc_info=True
        )
        raise


def handle_dns_action(instance_id, hostname, action):
    try:
        if not HOSTED_ZONE_ID:
            logger.error("Hosted Zone ID is not available.")
            return

        # Fetch hosted zone details
        hosted_zone = route53.get_hosted_zone(Id=HOSTED_ZONE_ID)
        zone_name = hosted_zone["HostedZone"]["Name"].rstrip(
            "."
        )  # Ensure no trailing dot
        logger.info(f"Fetched hosted zone name: {zone_name}")

        # Retrieve the instance's private IP address
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        logger.info(f"Instance details: {instance}")  # Log the entire response

        # Check if the PrivateIpAddress key exists
        private_ip = instance["Reservations"][0]["Instances"][0].get(
            "PrivateIpAddress", None
        )

        if not private_ip:
            logger.error(f"Private IP not found for instance {instance_id}")
            return

        if not hostname.endswith(zone_name):
            hostname = f"{hostname}.{zone_name}"
        logger.info(f"Fully qualified hostname: {hostname}")

        # Fetch existing records for the hostname
        existing_records = route53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID, StartRecordName=hostname, StartRecordType="A"
        )

        # Prepare the changes batch
        change_batch = {"Comment": f"{action} record for {hostname}", "Changes": []}

        logger.info(f"Action: {action}, Existing records: {existing_records}")

        # Check if the action is DELETE and the record exists
        if action == "DELETE":
            record_exists = False
            for record in existing_records["ResourceRecordSets"]:
                if record["Name"] == hostname and record["Type"] == "A":
                    record_exists = True
                    # Proceed to delete the record
                    change_batch["Changes"].append(
                        {
                            "Action": "DELETE",
                            "ResourceRecordSet": {
                                "Name": hostname,
                                "Type": "A",
                                "ResourceRecords": record["ResourceRecords"],
                            },
                        }
                    )
                    break

            if not record_exists:
                logger.info(
                    f"DNS record for {hostname} does not exist, skipping DELETE."
                )
                return  # Skip if the record doesn't exist

        # If action is CREATE or UPSERT, handle it
        elif action == "CREATE":
            # Check if the record already exists to prevent duplicate entries
            record_exists = False
            for record in existing_records["ResourceRecordSets"]:
                if record["Name"] == hostname and record["Type"] == "A":
                    record_exists = True
                    # Add the new IP to existing records if it doesn't already exist
                    if not any(
                        r["Value"] == private_ip for r in record["ResourceRecords"]
                    ):
                        record["ResourceRecords"].append({"Value": private_ip})
                        change_batch["Changes"].append(
                            {"Action": "UPSERT", "ResourceRecordSet": record}
                        )
                    break

            # Only create the record if it doesn't exist
            if not record_exists:
                change_batch["Changes"].append(
                    {
                        "Action": "CREATE",
                        "ResourceRecordSet": {
                            "Name": hostname,
                            "Type": "A",
                            "TTL": TTL,  # Use the globally defined TTL variable
                            "ResourceRecords": [{"Value": private_ip}],
                        },
                    }
                )

        # Update Route 53 if there are changes
        if change_batch["Changes"]:
            logger.info(f"Updating Route 53: {change_batch}")
            response = route53.change_resource_record_sets(
                HostedZoneId=HOSTED_ZONE_ID, ChangeBatch=change_batch
            )
            logger.info(f"Route 53 response: {response}")
        else:
            logger.info(f"No changes needed for {hostname}.")

    except Exception as e:
        logger.error(
            f"Failed to {action} DNS record for {instance_id}: {str(e)}", exc_info=True
        )
        raise


def complete_lifecycle_action(asg_name, hook_name, token, result):
    try:
        logger.info(
            f"Completing lifecycle action: {asg_name}, {hook_name}, {token}, {result}"
        )
        response = autoscaling.complete_lifecycle_action(
            AutoScalingGroupName=asg_name,
            LifecycleHookName=hook_name,
            LifecycleActionToken=token,
            LifecycleActionResult=result,
        )
        logger.info(f"Lifecycle action completed: {response}")
    except Exception as e:
        logger.error(f"Failed to complete lifecycle action: {str(e)}", exc_info=True)
        raise
