locals {
  budget_notification_types = var.enable_budgets ? toset(["ACTUAL", "FORECASTED"]) : toset([])
  budget_thresholds         = toset([1, 10, 25, 40])
}

resource "aws_budgets_budget" "campaign" {
  for_each = local.budget_notification_types

  name         = "${local.name}-${lower(each.key)}"
  budget_type  = "COST"
  limit_amount = tostring(var.campaign_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = local.budget_thresholds
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = each.key
      subscriber_email_addresses = [var.budget_notification_email]
      subscriber_sns_topic_arns = (
        local.budget_kill_switch_topic_enabled &&
        notification.value == local.budget_kill_switch_threshold_usd
        ? [aws_sns_topic.budget_kill_switch[0].arn]
        : []
      )
    }
  }

  # AWS Budgets validates topic publishing authority when it creates subscribers.
  depends_on = [aws_sns_topic_policy.budget_kill_switch]
}
