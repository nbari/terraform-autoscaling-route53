# terraform-autoscaling-route53

Create DNS A records for instances within and autoscaling group

Usage:

If you have a structure like the following:

```
.
├── applications
├── logs
├── services
├── setup
└── vpc
```

In your `vpc/route53.tf` file add the following:

```hcl
resource "aws_route53_zone" "private" {
  name    = var.vpc_domain_name
  comment = "private zone"
  vpc {
    vpc_id = aws_vpc.main.id
  }
}

output "private-zone-id" {
  value = aws_route53_zone.private.id
}

module "autoscaling-route53" {
  source  = "nbari/autoscaling-route53/aws"
  version = "x.y.z"

  zone_id = aws_route53_zone.private.id
}

output "autoscaling-route53" {
  value = module.autoscaling-route53
}
```

Optionally you can change the following variables, defaults are shown below:

```hcl
name      = "autoscaling-route53"
ttl       = 60
log_level = "INFO"
```

## Applications (ASG)

In your applications directory where you have your autoscaling groups, you can add the following:

```hcl
data "terraform_remote_state" "vpc" {
  backend = "s3"

  config = {
    bucket = "<bucket>"
    key    = "vpc/terraform.tfstate"
    region = "<region>"
  }
}

resource "aws_autoscaling_lifecycle_hook" "hook-launching" {
  name                    = "lifecycle-launching"
  autoscaling_group_name  = var.name # <-- the name of your autoscaling group
  lifecycle_transition    = "autoscaling:EC2_INSTANCE_LAUNCHING"
  default_result          = CONTINUE
  heartbeat_timeout       = 60
  notification_target_arn = data.terraform_remote_state.vpc.outputs.autoscaling-route53.sns_topic_arn
  role_arn                = data.terraform_remote_state.vpc.outputs.autoscaling-route53.lifecycle_iam_role_arn
  depends_on              = [aws_autoscaling_group.bg_asg]

}

resource "aws_autoscaling_lifecycle_hook" "hook-terminating" {
  name                    = "lifecycle-terminating"
  autoscaling_group_name  = var.name # <-- the name of your autoscaling group
  lifecycle_transition    = "autoscaling:EC2_INSTANCE_TERMINATING"
  default_result          = CONTINUE
  heartbeat_timeout       = 60
  notification_target_arn = data.terraform_remote_state.vpc.outputs.autoscaling-route53.sns_topic_arn
  role_arn                = data.terraform_remote_state.vpc.outputs.autoscaling-route53.lifecycle_iam_role_arn
  depends_on              = [aws_autoscaling_group.bg_asg]
}
```
