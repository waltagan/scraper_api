{
  "batch_id": "81a9d43e",
  "status": "completed",
  "total": 250,
  "processed": 250,
  "success_count": 146,
  "error_count": 104,
  "success_rate_pct": 58.4,
  "remaining": 0,
  "in_progress": 0,
  "peak_in_progress": 250,
  "throughput_per_min": 164.7,
  "eta_minutes": null,
  "elapsed_seconds": 91.1,
  "flushes_done": 10,
  "buffer_size": 0,
  "processing_time_ms": {
    "avg": 39015.9,
    "min": 3648.6,
    "max": 62605.7,
    "p50": 35562.4,
    "p60": 45630.9,
    "p70": 47421.4,
    "p80": 49863.1,
    "p90": 58544.9,
    "p95": 60115.1,
    "p99": 60345.9
  },
  "error_breakdown": {
    "timeout": 92,
    "other": 6,
    "blocked": 3,
    "connection": 2,
    "empty_content": 1
  },
  "pages_per_company_avg": 4.4,
  "total_retries": 0,
  "failure_diagnosis": {
    "total_failures": 104,
    "total_processed": 250,
    "failure_rate_pct": 41.6,
    "categories": {
      "site_offline": {
        "count": 5,
        "pct_of_failures": 4.8,
        "pct_of_total": 2,
        "breakdown": {
          "probe:refused": 4,
          "probe:server_error": 1
        }
      },
      "proxy_infra": {
        "count": 96,
        "pct_of_failures": 92.3,
        "pct_of_total": 38.4,
        "breakdown": {
          "proxy:timeout": 82,
          "probe:timeout": 10,
          "proxy:connection": 2,
          "proxy:other": 1,
          "proxy:empty_response": 1
        }
      },
      "blocked": {
        "count": 3,
        "pct_of_failures": 2.9,
        "pct_of_total": 1.2,
        "breakdown": {
          "proxy:http_403": 3
        }
      }
    }
  },
  "stage_funnel": {
    "probe": {
      "entered": 250,
      "ok": 235,
      "fail": 15,
      "success_rate_pct": 94,
      "fail_reasons": {
        "probe:timeout": 10,
        "probe:refused": 4,
        "probe:server_error": 1
      },
      "time_ms": {
        "p50": 4551.6,
        "p75": 5298.6,
        "p90": 9180.2,
        "p95": 24836.9,
        "p99": 27465.6
      }
    },
    "main_page": {
      "entered": 235,
      "ok": 146,
      "fail": 89,
      "success_rate_pct": 62.1,
      "fail_reasons": {
        "proxy:timeout": 82,
        "proxy:http_403": 3,
        "proxy:connection": 2,
        "proxy:other": 1,
        "proxy:empty_response": 1
      },
      "time_ms": {
        "p50": 12341,
        "p75": 28604.1,
        "p90": 30799.6,
        "p95": 32383.7,
        "p99": 33905.8
      }
    },
    "subpages": {
      "entered": 146,
      "attempted": 1335,
      "ok": 495,
      "fail": 840,
      "success_rate_pct": 37.1,
      "fail_reasons": {
        "scrape_fail": 334,
        "empty_content": 10
      },
      "time_ms": {
        "p50": 36981.3,
        "p75": 42482.8,
        "p90": 45975.5,
        "p95": 46847.9,
        "p99": 47505.1
      }
    },
    "overall_funnel_pct": 58.4
  },
  "subpage_pipeline": {
    "links_in_html_total": 4010,
    "links_after_filter": 4010,
    "links_selected": 1335,
    "avg_links_per_company": 16,
    "avg_selected_per_company": 5.3,
    "link_filter_rate_pct": 66.7,
    "zero_links_companies": 6,
    "zero_links_pct": 2.4,
    "main_page_failures": 104,
    "main_page_success_rate_pct": 58.4,
    "main_page_fail_reasons": {
      "proxy:timeout": 82,
      "probe:timeout": 10,
      "probe:refused": 4,
      "proxy:http_403": 3,
      "proxy:connection": 2,
      "proxy:other": 1,
      "proxy:empty_response": 1,
      "probe:server_error": 1
    },
    "subpages_attempted": 1335,
    "subpages_ok": 495,
    "subpages_failed": 840,
    "subpage_success_rate_pct": 37.1,
    "avg_subpages_per_company": 5.3,
    "subpage_error_breakdown": {
      "scrape_fail": 334,
      "empty_content": 10
    }
  },
  "infrastructure": {
    "proxy": {
      "loaded": true,
      "mode": "direct_ip",
      "gateway_url": "http://USER927913-zone-custom-region-BR:2dd94a@165...",
      "health_checked": true,
      "total_requests": 0,
      "successes": 0,
      "failures": 0,
      "success_rate": "N/A",
      "health_check": {
        "mode": "direct_ip",
        "healthy": true,
        "tests_ok": 3,
        "tests_failed": 0,
        "latency_ms": {
          "avg": 1191.8
        },
        "errors": null
      }
    },
    "config": {
      "request_timeout": 12,
      "probe_timeout": 8,
      "max_retries": 1,
      "retry_delay": 0,
      "max_subpages": 15,
      "per_domain_concurrent": 8,
      "workers_per_instance": 200,
      "num_instances": 5,
      "flush_size": 1000,
      "min_content_length": 100
    }
  },
  "last_errors": [],
  "instances": [
    {
      "id": 0,
      "status": "completed",
      "processed": 25,
      "success": 16,
      "errors": 9,
      "throughput_per_min": 17.3
    },
    {
      "id": 1,
      "status": "completed",
      "processed": 25,
      "success": 9,
      "errors": 16,
      "throughput_per_min": 17.3
    },
    {
      "id": 2,
      "status": "completed",
      "processed": 25,
      "success": 15,
      "errors": 10,
      "throughput_per_min": 17.3
    },
    {
      "id": 3,
      "status": "completed",
      "processed": 25,
      "success": 15,
      "errors": 10,
      "throughput_per_min": 17.3
    },
    {
      "id": 4,
      "status": "completed",
      "processed": 25,
      "success": 13,
      "errors": 12,
      "throughput_per_min": 17.3
    },
    {
      "id": 5,
      "status": "completed",
      "processed": 25,
      "success": 13,
      "errors": 12,
      "throughput_per_min": 17.3
    },
    {
      "id": 6,
      "status": "completed",
      "processed": 25,
      "success": 18,
      "errors": 7,
      "throughput_per_min": 17.3
    },
    {
      "id": 7,
      "status": "completed",
      "processed": 25,
      "success": 17,
      "errors": 8,
      "throughput_per_min": 17.3
    },
    {
      "id": 8,
      "status": "completed",
      "processed": 25,
      "success": 15,
      "errors": 10,
      "throughput_per_min": 17.3
    },
    {
      "id": 9,
      "status": "completed",
      "processed": 25,
      "success": 15,
      "errors": 10,
      "throughput_per_min": 17.3
    }
  ]
}