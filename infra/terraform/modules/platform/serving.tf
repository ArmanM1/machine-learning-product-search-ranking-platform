resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_lambda_function" "api" {
  count = var.enable_serving ? 1 : 0

  function_name                  = "${local.name}-api"
  role                           = aws_iam_role.lambda.arn
  package_type                   = "Image"
  image_uri                      = var.serving_image_uri
  architectures                  = ["x86_64"]
  memory_size                    = var.lambda_memory_mb
  timeout                        = var.lambda_timeout_seconds
  reserved_concurrent_executions = var.lambda_reserved_concurrency
  publish                        = true

  ephemeral_storage {
    size = var.lambda_ephemeral_storage_mb
  }

  environment {
    variables = {
      ARTIFACT_BUCKET              = aws_s3_bucket.artifacts.id
      AWS_REGION_NAME              = var.aws_region
      ENVIRONMENT                  = var.environment
      LOG_LEVEL                    = "INFO"
      PUBLIC_PREFIX                = "public/"
      SEARCH_RANK_RELEASE_MANIFEST = "/var/task/release/release-manifest.json"
      SEARCH_RANK_CURATED_QUERIES  = "/var/task/release/curated-queries.json"
      SEARCH_RANK_PUBLIC_EVIDENCE  = "/var/task/release/public-evidence.json"
      SEARCH_RANK_RELEASE_MODE     = "true"
      SEARCH_RANK_WEB_DIST         = "/var/task/web/dist"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
  tags       = local.common_tags
}

resource "aws_lambda_alias" "candidate" {
  count = var.enable_serving ? 1 : 0

  name             = "candidate"
  description      = "Newest immutable revision; smoke-test before production promotion"
  function_name    = aws_lambda_function.api[0].function_name
  function_version = aws_lambda_function.api[0].version
}

resource "aws_lambda_alias" "production" {
  count = var.enable_serving ? 1 : 0

  name             = "production"
  description      = "Last healthy revision; changed only by the gated deploy workflow"
  function_name    = aws_lambda_function.api[0].function_name
  function_version = aws_lambda_function.api[0].version

  lifecycle {
    ignore_changes = [function_version]
  }
}

resource "aws_apigatewayv2_api" "candidate" {
  count = var.enable_serving ? 1 : 0

  name          = "${local.name}-candidate"
  protocol_type = "HTTP"
  description   = "Candidate-alias smoke-test API; never linked from the public site"
  tags          = local.common_tags
}

resource "aws_apigatewayv2_integration" "candidate" {
  count = var.enable_serving ? 1 : 0

  api_id                 = aws_apigatewayv2_api.candidate[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.candidate[0].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "candidate" {
  count = var.enable_serving ? 1 : 0

  api_id             = aws_apigatewayv2_api.candidate[0].id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.candidate[0].id}"
  authorization_type = "AWS_IAM"
}

resource "aws_cloudwatch_log_group" "candidate_api" {
  name              = "/aws/apigateway/${local.name}-candidate"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_apigatewayv2_stage" "candidate" {
  count = var.enable_serving ? 1 : 0

  api_id      = aws_apigatewayv2_api.candidate[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 2
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.candidate_api.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      integrationErr = "$context.integrationErrorMessage"
    })
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_api" "production" {
  count = var.enable_serving ? 1 : 0

  name          = "${local.name}-production"
  protocol_type = "HTTP"
  description   = "Public API backed by the production Lambda alias"
  tags          = local.common_tags
}

resource "aws_apigatewayv2_integration" "production" {
  count = var.enable_serving ? 1 : 0

  api_id                 = aws_apigatewayv2_api.production[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.production[0].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "production" {
  count = var.enable_serving ? 1 : 0

  api_id    = aws_apigatewayv2_api.production[0].id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.production[0].id}"
}

resource "aws_cloudwatch_log_group" "production_api" {
  name              = "/aws/apigateway/${local.name}-production"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.common_tags
}

resource "aws_apigatewayv2_stage" "production" {
  count = var.enable_serving ? 1 : 0

  api_id      = aws_apigatewayv2_api.production[0].id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 2
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.production_api.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      integrationErr = "$context.integrationErrorMessage"
    })
  }

  tags = local.common_tags
}

resource "aws_lambda_permission" "candidate_api" {
  count = var.enable_serving ? 1 : 0

  statement_id  = "AllowCandidateApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  qualifier     = aws_lambda_alias.candidate[0].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.candidate[0].execution_arn}/*/*"
}

resource "aws_lambda_permission" "production_api" {
  count = var.enable_serving ? 1 : 0

  statement_id  = "AllowProductionApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  qualifier     = aws_lambda_alias.production[0].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.production[0].execution_arn}/*/*"
}

resource "aws_cloudfront_origin_access_control" "site" {
  count = var.enable_serving ? 1 : 0

  name                              = "${local.name}-site"
  description                       = "SigV4 access to the private static-site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_cloudfront_cache_policy" "optimized" {
  count = var.enable_serving ? 1 : 0
  name  = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  count = var.enable_serving ? 1 : 0
  name  = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  count = var.enable_serving ? 1 : 0
  name  = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  count = var.enable_serving ? 1 : 0

  name = "${local.name}-security"

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'"
      override                = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }

    xss_protection {
      mode_block = true
      protection = true
      override   = true
    }
  }
}

resource "aws_cloudfront_function" "spa_rewrite" {
  count = var.enable_serving ? 1 : 0

  name    = "${local.name}-spa-rewrite"
  runtime = "cloudfront-js-1.0"
  comment = "Rewrite extensionless static routes to the SPA entry point"
  publish = true
  code    = <<-JAVASCRIPT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      if (uri.endsWith('/')) {
        request.uri = uri + 'index.html';
      } else if (uri.indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  JAVASCRIPT
}

resource "aws_cloudfront_distribution" "site" {
  count = var.enable_serving ? 1 : 0

  enabled             = true
  is_ipv6_enabled     = true
  comment             = local.name
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "private-site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site[0].id
  }

  origin {
    domain_name = trimprefix(aws_apigatewayv2_api.production[0].api_endpoint, "https://")
    origin_id   = "production-api"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "private-site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized[0].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite[0].arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "production-api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled[0].id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host[0].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id
  }

  ordered_cache_behavior {
    path_pattern               = "/healthz"
    target_origin_id           = "production-api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled[0].id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host[0].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id
  }

  ordered_cache_behavior {
    path_pattern               = "/readyz"
    target_origin_id           = "production-api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled[0].id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host[0].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = local.common_tags
}

data "aws_iam_policy_document" "site_cloudfront" {
  count = var.enable_serving ? 1 : 0

  statement {
    sid     = "CloudFrontReadOnly"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.site.arn}/*",
    ]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site[0].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  count = var.enable_serving ? 1 : 0

  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_cloudfront[0].json
}
