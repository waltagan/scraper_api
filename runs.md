run1 
{
  "batch_id": "4f596149",
  "status": "running",
  "total": 2000,
  "processed": 1834,
  "success_count": 1100,
  "error_count": 734,
  "success_rate_pct": 60,
  "remaining": 166,
  "in_progress": 166,
  "peak_in_progress": 2000,
  "throughput_per_min": 304.6,
  "eta_minutes": 0.5,
  "elapsed_seconds": 361.3,
  "flushes_done": 0,
  "buffer_size": 1834,
  "processing_time_ms": {
    "avg": 194477.2,
    "min": 4231.5,
    "max": 358581.8,
    "p50": 196681.2,
    "p60": 214357,
    "p70": 233946.2,
    "p80": 276854.8,
    "p90": 320676.5,
    "p95": 341912,
    "p99": 357000.8
  },
  "error_breakdown": {
    "empty_content": 734
  },
  "pages_per_company_avg": 1.6,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 33074,
    "links_after_filter": 33074,
    "links_selected": 18857,
    "links_per_company_avg": 18,
    "selected_per_company_avg": 10.3,
    "zero_links_companies": 81,
    "zero_links_pct": 4.4,
    "main_page_failures": 734,
    "subpages_attempted": 10472,
    "subpages_ok": 694,
    "subpages_failed": 9778,
    "subpage_success_rate_pct": 6.6,
    "subpage_error_breakdown": {
      "timeout_slot": 2550,
      "scrape_fail": 2305,
      "circuit_open": 133
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 1000,
      "proxy_allocations": 15812,
      "total_outcomes": 14416,
      "successful": 1852,
      "failed": 12564,
      "success_rate": "12.8%"
    },
    "concurrency": {
      "active_requests": 193,
      "total_requests": 7993,
      "peak_concurrent": 1137,
      "global_limit": 5000,
      "per_domain_limit": 25,
      "slow_domains_count": 1051,
      "tracked_domains": 1075,
      "utilization": "3.9%"
    },
    "rate_limiter": {
      "domains_tracked": 967,
      "slow_domains_count": 0,
      "total_requests": 10641,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 967,
      "states": {
        "closed": 229,
        "open": 101,
        "half_open": 637
      },
      "total_blocked": 133,
      "total_opened": 739,
      "config": {
        "failure_threshold": 5,
        "recovery_timeout": 60,
        "half_open_max_tests": 2
      }
    }
  },
  "last_errors": [],
  "instances": [
    {
      "id": 0,
      "status": "running",
      "processed": 197,
      "success": 108,
      "errors": 89,
      "throughput_per_min": 32.9
    },
    {
      "id": 1,
      "status": "running",
      "processed": 140,
      "success": 78,
      "errors": 62,
      "throughput_per_min": 23.4
    },
    {
      "id": 2,
      "status": "running",
      "processed": 177,
      "success": 133,
      "errors": 44,
      "throughput_per_min": 29.5
    },
    {
      "id": 3,
      "status": "running",
      "processed": 177,
      "success": 131,
      "errors": 46,
      "throughput_per_min": 29.5
    },
    {
      "id": 4,
      "status": "running",
      "processed": 191,
      "success": 74,
      "errors": 117,
      "throughput_per_min": 31.9
    },
    {
      "id": 5,
      "status": "running",
      "processed": 197,
      "success": 100,
      "errors": 97,
      "throughput_per_min": 32.9
    },
    {
      "id": 6,
      "status": "running",
      "processed": 197,
      "success": 128,
      "errors": 69,
      "throughput_per_min": 32.9
    },
    {
      "id": 7,
      "status": "running",
      "processed": 184,
      "success": 111,
      "errors": 73,
      "throughput_per_min": 30.7
    },
    {
      "id": 8,
      "status": "running",
      "processed": 190,
      "success": 120,
      "errors": 70,
      "throughput_per_min": 31.7
    },
    {
      "id": 9,
      "status": "running",
      "processed": 184,
      "success": 117,
      "errors": 67,
      "throughput_per_min": 30.7
    }
  ]
}

run2 - meio da run 

{
  "batch_id": "4fb7c09a",
  "status": "running",
  "total": 2000,
  "processed": 1999,
  "success_count": 1172,
  "error_count": 827,
  "success_rate_pct": 58.6,
  "remaining": 1,
  "in_progress": 1,
  "peak_in_progress": 2000,
  "throughput_per_min": 293.2,
  "eta_minutes": 0,
  "elapsed_seconds": 409.1,
  "flushes_done": 9,
  "buffer_size": 199,
  "processing_time_ms": {
    "avg": 178101.7,
    "min": 3465.5,
    "max": 401876.4,
    "p50": 158165.1,
    "p60": 178506.1,
    "p70": 229151.6,
    "p80": 266696.9,
    "p90": 326694.3,
    "p95": 358175.3,
    "p99": 392854.7
  },
  "error_breakdown": {
    "empty_content": 827
  },
  "pages_per_company_avg": 3.9,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 48105,
    "links_after_filter": 48105,
    "links_selected": 23250,
    "links_per_company_avg": 24.1,
    "selected_per_company_avg": 11.6,
    "zero_links_companies": 73,
    "zero_links_pct": 3.7,
    "main_page_failures": 827,
    "subpages_attempted": 12801,
    "subpages_ok": 3437,
    "subpages_failed": 9364,
    "subpage_success_rate_pct": 26.8,
    "subpage_error_breakdown": {
      "timeout_slot": 3296,
      "scrape_fail": 2474,
      "circuit_open": 132
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 1000,
      "proxy_allocations": 15055,
      "total_outcomes": 15754,
      "successful": 4670,
      "failed": 11084,
      "success_rate": "29.6%"
    },
    "concurrency": {
      "active_requests": 2,
      "total_requests": 9380,
      "peak_concurrent": 2481,
      "global_limit": 5000,
      "per_domain_limit": 25,
      "slow_domains_count": 1014,
      "tracked_domains": 1123,
      "utilization": "0.0%"
    },
    "rate_limiter": {
      "domains_tracked": 1030,
      "slow_domains_count": 0,
      "total_requests": 12676,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 1030,
      "states": {
        "closed": 669,
        "open": 9,
        "half_open": 352
      },
      "total_blocked": 132,
      "total_opened": 367,
      "config": {
        "failure_threshold": 12,
        "recovery_timeout": 30,
        "half_open_max_tests": 3
      }
    }
  },
  "last_errors": [],
  "instances": [
    {
      "id": 0,
      "status": "completed",
      "processed": 200,
      "success": 123,
      "errors": 77,
      "throughput_per_min": 29.4
    },
    {
      "id": 1,
      "status": "completed",
      "processed": 200,
      "success": 109,
      "errors": 91,
      "throughput_per_min": 29.4
    },
    {
      "id": 2,
      "status": "completed",
      "processed": 200,
      "success": 123,
      "errors": 77,
      "throughput_per_min": 29.4
    },
    {
      "id": 3,
      "status": "completed",
      "processed": 200,
      "success": 113,
      "errors": 87,
      "throughput_per_min": 29.4
    },
    {
      "id": 4,
      "status": "completed",
      "processed": 200,
      "success": 124,
      "errors": 76,
      "throughput_per_min": 29.4
    },
    {
      "id": 5,
      "status": "completed",
      "processed": 200,
      "success": 128,
      "errors": 72,
      "throughput_per_min": 29.5
    },
    {
      "id": 6,
      "status": "completed",
      "processed": 200,
      "success": 108,
      "errors": 92,
      "throughput_per_min": 29.5
    },
    {
      "id": 7,
      "status": "completed",
      "processed": 200,
      "success": 93,
      "errors": 107,
      "throughput_per_min": 29.5
    },
    {
      "id": 8,
      "status": "completed",
      "processed": 200,
      "success": 123,
      "errors": 77,
      "throughput_per_min": 29.5
    },
    {
      "id": 9,
      "status": "running",
      "processed": 199,
      "success": 128,
      "errors": 71,
      "throughput_per_min": 29.3
    }
  ]
}
