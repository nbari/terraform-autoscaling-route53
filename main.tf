resource "aws_sns_topic" "autoscaling_route53" {
  name = var.name
}

resource "aws_iam_role_policy" "autoscaling_route53" {
  name = var.name
  role = aws_iam_role.autoscaling_route53.name

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Action":[
        "autoscaling:DescribeTags",
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:CompleteLifecycleAction",
        "ec2:DescribeInstances",
        "route53:GetHostedZone",
        "ec2:CreateTags"
      ],
      "Effect":"Allow",
      "Resource":"*"
    },
    {
      "Action":[
        "route53:ChangeResourceRecordSets",
        "route53:ListResourceRecordSets"
      ],
      "Effect":"Allow",
      "Resource":"arn:aws:route53:::hostedzone/${var.zone_id}"
    }
  ]
}
EOF

}

resource "aws_iam_role" "autoscaling_route53" {
  name = var.name

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF

}

resource "aws_iam_role" "lifecycle" {
  name               = "${var.name}-lifecycle"
  assume_role_policy = data.aws_iam_policy_document.lifecycle.json
}

data "aws_iam_policy_document" "lifecycle" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["autoscaling.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "lifecycle_policy" {
  name   = "${var.name}-lifecycle"
  role   = aws_iam_role.lifecycle.id
  policy = data.aws_iam_policy_document.lifecycle_policy.json
}

data "aws_iam_policy_document" "lifecycle_policy" {
  statement {
    effect    = "Allow"
    actions   = ["sns:Publish", "autoscaling:CompleteLifecycleAction"]
    resources = [aws_sns_topic.autoscaling_route53.arn]
  }
}

data "archive_file" "autoscaling_route53" {
  type        = "zip"
  source_file = "${path.module}/lambda/autoscaling_route53.py"
  output_path = "${path.module}/dist/autoscaling_route53.zip"
}

resource "aws_lambda_function" "autoscaling_route53" {
  depends_on = [aws_sns_topic.autoscaling_route53]

  filename         = data.archive_file.autoscaling_route53.output_path
  function_name    = var.name
  role             = aws_iam_role.autoscaling_route53.arn
  handler          = "autoscaling_route53.lambda_handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256(data.archive_file.autoscaling_route53.output_path)
  description      = "Handles DNS for autoscaling groups by receiving autoscaling notifications and setting/deleting records from route53"
  environment {
    variables = {
      "TTL"     = var.ttl
      "ZONE_ID" = var.zone_id
    }
  }
}

resource "aws_lambda_permission" "autoscaling_route53" {
  depends_on = [aws_lambda_function.autoscaling_route53]

  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.autoscaling_route53.arn
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.autoscaling_route53.arn
}

resource "aws_sns_topic_subscription" "autoscaling_route53" {
  depends_on = [aws_lambda_permission.autoscaling_route53]

  topic_arn = aws_sns_topic.autoscaling_route53.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.autoscaling_route53.arn
}
