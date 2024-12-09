output "sns_topic_arn" {
  description = "SNS topic ARN for autoscaling group"
  value       = aws_sns_topic.autoscaling_route53.arn
}

output "iam_role_arn" {
  description = "IAM role ARN for autoscaling group"
  value       = aws_iam_role.autoscaling_route53.arn
}

output "lifecycle_iam_role_arn" {
  description = "IAM Role ARN for lifecycle_hooks"
  value       = aws_iam_role.lifecycle.arn
}
