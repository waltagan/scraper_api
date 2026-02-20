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


run3 {
  "batch_id": "05f93eed",
  "status": "completed",
  "total": 2000,
  "processed": 2000,
  "success_count": 968,
  "error_count": 1032,
  "success_rate_pct": 48.4,
  "remaining": 0,
  "in_progress": 0,
  "peak_in_progress": 2000,
  "throughput_per_min": 211.9,
  "eta_minutes": null,
  "elapsed_seconds": 566.2,
  "flushes_done": 10,
  "buffer_size": 0,
  "processing_time_ms": {
    "avg": 251264.3,
    "min": 2914.9,
    "max": 520783.2,
    "p50": 234493.8,
    "p60": 256683.5,
    "p70": 315500.6,
    "p80": 363598.5,
    "p90": 435272.5,
    "p95": 471721.1,
    "p99": 495689.2
  },
  "error_breakdown": {
    "empty_content": 1032
  },
  "pages_per_company_avg": 7,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 29779,
    "links_after_filter": 29779,
    "links_selected": 17527,
    "links_per_company_avg": 14.9,
    "selected_per_company_avg": 8.8,
    "zero_links_companies": 74,
    "zero_links_pct": 3.7,
    "main_page_failures": 1032,
    "subpages_attempted": 10107,
    "subpages_ok": 5812,
    "subpages_failed": 4295,
    "subpage_success_rate_pct": 57.5,
    "subpage_error_breakdown": {
      "scrape_fail": 1602,
      "timeout_slot": 355
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 1000,
      "proxy_allocations": 35980,
      "total_outcomes": 27518,
      "successful": 6828,
      "failed": 20690,
      "success_rate": "24.8%"
    },
    "concurrency": {
      "active_requests": 0,
      "total_requests": 20492,
      "peak_concurrent": 2716,
      "global_limit": 15000,
      "per_domain_limit": 25,
      "slow_domains_count": 846,
      "tracked_domains": 931,
      "utilization": "0.0%"
    },
    "rate_limiter": {
      "domains_tracked": 846,
      "slow_domains_count": 0,
      "total_requests": 22714,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 846,
      "states": {
        "closed": 846,
        "open": 0,
        "half_open": 0
      },
      "total_blocked": 0,
      "total_opened": 0,
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
      "success": 103,
      "errors": 97,
      "throughput_per_min": 21.3
    },
    {
      "id": 1,
      "status": "completed",
      "processed": 200,
      "success": 106,
      "errors": 94,
      "throughput_per_min": 21.3
    },
    {
      "id": 2,
      "status": "completed",
      "processed": 200,
      "success": 101,
      "errors": 99,
      "throughput_per_min": 21.3
    },
    {
      "id": 3,
      "status": "completed",
      "processed": 200,
      "success": 108,
      "errors": 92,
      "throughput_per_min": 21.3
    },
    {
      "id": 4,
      "status": "completed",
      "processed": 200,
      "success": 92,
      "errors": 108,
      "throughput_per_min": 21.3
    },
    {
      "id": 5,
      "status": "completed",
      "processed": 200,
      "success": 87,
      "errors": 113,
      "throughput_per_min": 21.3
    },
    {
      "id": 6,
      "status": "completed",
      "processed": 200,
      "success": 96,
      "errors": 104,
      "throughput_per_min": 21.3
    },
    {
      "id": 7,
      "status": "completed",
      "processed": 200,
      "success": 94,
      "errors": 106,
      "throughput_per_min": 21.3
    },
    {
      "id": 8,
      "status": "completed",
      "processed": 200,
      "success": 88,
      "errors": 112,
      "throughput_per_min": 21.3
    },
    {
      "id": 9,
      "status": "completed",
      "processed": 200,
      "success": 93,
      "errors": 107,
      "throughput_per_min": 21.3
    }
  ]
}


run4

{
  "batch_id": "96eed17d",
  "status": "running",
  "total": 2000,
  "processed": 1853,
  "success_count": 786,
  "error_count": 1067,
  "success_rate_pct": 42.4,
  "remaining": 147,
  "in_progress": 147,
  "peak_in_progress": 2000,
  "throughput_per_min": 156.4,
  "eta_minutes": 0.9,
  "elapsed_seconds": 711,
  "flushes_done": 0,
  "buffer_size": 1653,
  "processing_time_ms": {
    "avg": 485389.7,
    "min": 4029.4,
    "max": 681009.3,
    "p50": 512937.7,
    "p60": 547481.7,
    "p70": 554862.1,
    "p80": 574469.5,
    "p90": 608378.3,
    "p95": 645042.9,
    "p99": 671721.9
  },
  "error_breakdown": {
    "empty_content": 1067
  },
  "pages_per_company_avg": 5.9,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 27474,
    "links_after_filter": 27474,
    "links_selected": 15459,
    "links_per_company_avg": 14.8,
    "selected_per_company_avg": 8.3,
    "zero_links_companies": 34,
    "zero_links_pct": 1.8,
    "main_page_failures": 1067,
    "subpages_attempted": 7946,
    "subpages_ok": 3857,
    "subpages_failed": 4089,
    "subpage_success_rate_pct": 48.5,
    "subpage_error_breakdown": {
      "scrape_fail": 1388,
      "timeout_slot": 85
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 1000,
      "active_proxies": 998,
      "health_checked": true,
      "proxy_allocations": 40120,
      "total_outcomes": 31713,
      "successful": 5078,
      "failed": 26635,
      "success_rate": "16.0%",
      "health_check": {
        "total_tested": 1000,
        "healthy": 998,
        "dead": 2,
        "healthy_pct": 99.8,
        "pool_active": 998,
        "check_time_ms": 22578,
        "latency_ms": {
          "avg": 1071,
          "min": 682.9,
          "max": 2868,
          "p50": 1034.6,
          "p95": 1552.1
        },
        "error_breakdown": {
          "TimeoutError": 1,
          "status_502": 1
        }
      }
    },
    "concurrency": {
      "active_requests": 223,
      "total_requests": 26839,
      "peak_concurrent": 4318,
      "global_limit": 15000,
      "per_domain_limit": 25,
      "slow_domains_count": 795,
      "tracked_domains": 821,
      "utilization": "1.5%"
    },
    "rate_limiter": {
      "domains_tracked": 769,
      "slow_domains_count": 0,
      "total_requests": 31035,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 769,
      "states": {
        "closed": 769,
        "open": 0,
        "half_open": 0
      },
      "total_blocked": 0,
      "total_opened": 0,
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
      "status": "running",
      "processed": 196,
      "success": 124,
      "errors": 72,
      "throughput_per_min": 17.1
    },
    {
      "id": 1,
      "status": "running",
      "processed": 200,
      "success": 98,
      "errors": 102,
      "throughput_per_min": 17.5
    },
    {
      "id": 2,
      "status": "running",
      "processed": 194,
      "success": 98,
      "errors": 96,
      "throughput_per_min": 16.9
    },
    {
      "id": 3,
      "status": "running",
      "processed": 188,
      "success": 94,
      "errors": 94,
      "throughput_per_min": 16.4
    },
    {
      "id": 4,
      "status": "running",
      "processed": 185,
      "success": 76,
      "errors": 109,
      "throughput_per_min": 16.2
    },
    {
      "id": 5,
      "status": "running",
      "processed": 188,
      "success": 82,
      "errors": 106,
      "throughput_per_min": 16.4
    },
    {
      "id": 6,
      "status": "running",
      "processed": 184,
      "success": 63,
      "errors": 121,
      "throughput_per_min": 16.1
    },
    {
      "id": 7,
      "status": "running",
      "processed": 166,
      "success": 36,
      "errors": 130,
      "throughput_per_min": 14.5
    },
    {
      "id": 8,
      "status": "running",
      "processed": 198,
      "success": 67,
      "errors": 131,
      "throughput_per_min": 17.3
    },
    {
      "id": 9,
      "status": "running",
      "processed": 154,
      "success": 48,
      "errors": 106,
      "throughput_per_min": 13.5
    }
  ]
}

run5
{
  "batch_id": "ba6e5de5",
  "status": "running",
  "total": 2000,
  "processed": 1996,
  "success_count": 900,
  "error_count": 1096,
  "success_rate_pct": 45.1,
  "remaining": 4,
  "in_progress": 4,
  "peak_in_progress": 2000,
  "throughput_per_min": 200.5,
  "eta_minutes": 0,
  "elapsed_seconds": 597.4,
  "flushes_done": 6,
  "buffer_size": 796,
  "processing_time_ms": {
    "avg": 263852.7,
    "min": 3236.1,
    "max": 539555.9,
    "p50": 260283.5,
    "p60": 270688.4,
    "p70": 295027.3,
    "p80": 330161.2,
    "p90": 439132.9,
    "p95": 475173.6,
    "p99": 511668.6
  },
  "error_breakdown": {
    "empty_content": 1096
  },
  "pages_per_company_avg": 5.1,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 24261,
    "links_after_filter": 24261,
    "links_selected": 14428,
    "links_per_company_avg": 12.2,
    "selected_per_company_avg": 7.2,
    "zero_links_companies": 80,
    "zero_links_pct": 4,
    "main_page_failures": 1096,
    "subpages_attempted": 8476,
    "subpages_ok": 3669,
    "subpages_failed": 4807,
    "subpage_success_rate_pct": 43.3,
    "subpage_error_breakdown": {
      "scrape_fail": 2312,
      "timeout_slot": 190
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 2500,
      "active_proxies": 2493,
      "health_checked": true,
      "proxy_allocations": 33311,
      "total_outcomes": 24110,
      "successful": 4730,
      "failed": 19380,
      "success_rate": "19.6%",
      "per_proxy_analysis": {
        "proxies_analyzed": 2493,
        "proxies_used": 2493,
        "proxies_unused": 7,
        "success_rate_distribution": {
          "avg_pct": 19.5,
          "std_dev_pct": 12.6,
          "min_pct": 0,
          "max_pct": 66.7,
          "p10": 0,
          "p25": 10,
          "p50": 20,
          "p75": 27.3,
          "p90": 36.4
        },
        "buckets": {
          "90_100_pct": 0,
          "70_90_pct": 0,
          "50_70_pct": 44,
          "30_50_pct": 536,
          "10_30_pct": 1426,
          "0_10_pct": 487
        },
        "verdict": "MODERADA — variação moderada (std=13%). Maioria dos proxies performa similar, alguns outliers.",
        "worst_5": [
          {
            "proxy_id": ".200.81:6664",
            "requests": 14,
            "outcomes": 8,
            "successes": 0,
            "failures": 8,
            "success_rate_pct": 0
          },
          {
            "proxy_id": "197.223:6462",
            "requests": 14,
            "outcomes": 7,
            "successes": 0,
            "failures": 7,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".92.137:6071",
            "requests": 14,
            "outcomes": 7,
            "successes": 0,
            "failures": 7,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".102.94:5333",
            "requests": 14,
            "outcomes": 7,
            "successes": 0,
            "failures": 7,
            "success_rate_pct": 0
          },
          {
            "proxy_id": "3.91.81:6514",
            "requests": 14,
            "outcomes": 7,
            "successes": 0,
            "failures": 7,
            "success_rate_pct": 0
          }
        ],
        "best_5": [
          {
            "proxy_id": ".109.16:6949",
            "requests": 13,
            "outcomes": 9,
            "successes": 6,
            "failures": 3,
            "success_rate_pct": 66.7
          },
          {
            "proxy_id": "175.137:6410",
            "requests": 13,
            "outcomes": 9,
            "successes": 6,
            "failures": 3,
            "success_rate_pct": 66.7
          },
          {
            "proxy_id": ".109.91:7024",
            "requests": 13,
            "outcomes": 6,
            "successes": 4,
            "failures": 2,
            "success_rate_pct": 66.7
          },
          {
            "proxy_id": "172.211:6483",
            "requests": 13,
            "outcomes": 8,
            "successes": 5,
            "failures": 3,
            "success_rate_pct": 62.5
          },
          {
            "proxy_id": "101.130:6063",
            "requests": 13,
            "outcomes": 8,
            "successes": 5,
            "failures": 3,
            "success_rate_pct": 62.5
          }
        ]
      },
      "health_check": {
        "total_tested": 2500,
        "healthy": 2493,
        "dead": 7,
        "healthy_pct": 99.7,
        "pool_active": 2493,
        "check_time_ms": 54995,
        "latency_ms": {
          "avg": 1087.9,
          "min": 639.8,
          "max": 3493.8,
          "p50": 1015.8,
          "p95": 1662.2
        },
        "error_breakdown": {
          "status_502": 7
        }
      }
    },
    "concurrency": {
      "active_requests": 10,
      "total_requests": 18545,
      "peak_concurrent": 3918,
      "global_limit": 15000,
      "per_domain_limit": 25,
      "slow_domains_count": 738,
      "tracked_domains": 860,
      "utilization": "0.1%"
    },
    "rate_limiter": {
      "domains_tracked": 781,
      "slow_domains_count": 0,
      "total_requests": 20489,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 781,
      "states": {
        "closed": 780,
        "open": 0,
        "half_open": 1
      },
      "total_blocked": 0,
      "total_opened": 1,
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
      "success": 100,
      "errors": 100,
      "throughput_per_min": 22.2
    },
    {
      "id": 1,
      "status": "completed",
      "processed": 200,
      "success": 105,
      "errors": 95,
      "throughput_per_min": 22.2
    },
    {
      "id": 2,
      "status": "completed",
      "processed": 200,
      "success": 103,
      "errors": 97,
      "throughput_per_min": 22.2
    },
    {
      "id": 3,
      "status": "completed",
      "processed": 200,
      "success": 85,
      "errors": 115,
      "throughput_per_min": 22.2
    },
    {
      "id": 4,
      "status": "completed",
      "processed": 200,
      "success": 78,
      "errors": 122,
      "throughput_per_min": 22.2
    },
    {
      "id": 5,
      "status": "completed",
      "processed": 200,
      "success": 86,
      "errors": 114,
      "throughput_per_min": 22.2
    },
    {
      "id": 6,
      "status": "running",
      "processed": 198,
      "success": 105,
      "errors": 93,
      "throughput_per_min": 22
    },
    {
      "id": 7,
      "status": "running",
      "processed": 200,
      "success": 73,
      "errors": 127,
      "throughput_per_min": 22.2
    },
    {
      "id": 8,
      "status": "running",
      "processed": 199,
      "success": 96,
      "errors": 103,
      "throughput_per_min": 22.1
    },
    {
      "id": 9,
      "status": "running",
      "processed": 199,
      "success": 69,
      "errors": 130,
      "throughput_per_min": 22.1
    }
  ]
}

run7

{
  "batch_id": "7c34db4b",
  "status": "completed",
  "total": 2000,
  "processed": 2000,
  "success_count": 1003,
  "error_count": 997,
  "success_rate_pct": 50.1,
  "remaining": 0,
  "in_progress": 0,
  "peak_in_progress": 2000,
  "throughput_per_min": 133.7,
  "eta_minutes": null,
  "elapsed_seconds": 897.3,
  "flushes_done": 10,
  "buffer_size": 0,
  "processing_time_ms": {
    "avg": 373523.1,
    "min": 3164.9,
    "max": 822334.5,
    "p50": 386124.6,
    "p60": 422569.5,
    "p70": 453391,
    "p80": 486067,
    "p90": 535320.1,
    "p95": 563840.6,
    "p99": 723915.1
  },
  "error_breakdown": {
    "empty_content": 991,
    "timeout": 6
  },
  "pages_per_company_avg": 8.9,
  "total_retries": 12,
  "subpage_pipeline": {
    "links_in_html_total": 36822,
    "links_after_filter": 36822,
    "links_selected": 17855,
    "links_per_company_avg": 18.4,
    "selected_per_company_avg": 8.9,
    "zero_links_companies": 92,
    "zero_links_pct": 4.6,
    "main_page_failures": 991,
    "subpages_attempted": 9763,
    "subpages_ok": 7957,
    "subpages_failed": 1806,
    "subpage_success_rate_pct": 81.5,
    "subpage_error_breakdown": {
      "scrape_fail": 873,
      "timeout_slot": 37
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 2500,
      "active_proxies": 2497,
      "health_checked": true,
      "proxy_allocations": 31113,
      "total_outcomes": 22620,
      "successful": 9067,
      "failed": 13553,
      "success_rate": "40.1%",
      "per_proxy_analysis": {
        "proxies_analyzed": 2497,
        "proxies_used": 2497,
        "proxies_unused": 3,
        "success_rate_distribution": {
          "avg_pct": 40.4,
          "std_dev_pct": 17,
          "min_pct": 0,
          "max_pct": 100,
          "p10": 20,
          "p25": 28.6,
          "p50": 40,
          "p75": 50,
          "p90": 62.5
        },
        "buckets": {
          "90_100_pct": 1,
          "70_90_pct": 133,
          "50_70_pct": 705,
          "30_50_pct": 1033,
          "10_30_pct": 569,
          "0_10_pct": 56
        },
        "verdict": "MODERADA — variação moderada (std=17%). Maioria dos proxies performa similar, alguns outliers.",
        "worst_5": [
          {
            "proxy_id": ".254.27:6009",
            "requests": 13,
            "outcomes": 8,
            "successes": 0,
            "failures": 8,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".53.177:6916",
            "requests": 13,
            "outcomes": 8,
            "successes": 0,
            "failures": 8,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".25.120:5555",
            "requests": 13,
            "outcomes": 8,
            "successes": 0,
            "failures": 8,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".53.128:6867",
            "requests": 13,
            "outcomes": 8,
            "successes": 0,
            "failures": 8,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".253.48:6666",
            "requests": 13,
            "outcomes": 10,
            "successes": 0,
            "failures": 10,
            "success_rate_pct": 0
          }
        ],
        "best_5": [
          {
            "proxy_id": ".91.230:6663",
            "requests": 13,
            "outcomes": 5,
            "successes": 5,
            "failures": 0,
            "success_rate_pct": 100
          },
          {
            "proxy_id": "2.20.83:6015",
            "requests": 12,
            "outcomes": 9,
            "successes": 8,
            "failures": 1,
            "success_rate_pct": 88.9
          },
          {
            "proxy_id": "172.158:6430",
            "requests": 12,
            "outcomes": 8,
            "successes": 7,
            "failures": 1,
            "success_rate_pct": 87.5
          },
          {
            "proxy_id": "102.186:5425",
            "requests": 13,
            "outcomes": 8,
            "successes": 7,
            "failures": 1,
            "success_rate_pct": 87.5
          },
          {
            "proxy_id": "170.235:6204",
            "requests": 13,
            "outcomes": 8,
            "successes": 7,
            "failures": 1,
            "success_rate_pct": 87.5
          }
        ]
      },
      "health_check": {
        "total_tested": 2500,
        "healthy": 2497,
        "dead": 3,
        "healthy_pct": 99.9,
        "pool_active": 2497,
        "check_time_ms": 54688,
        "latency_ms": {
          "avg": 1072.6,
          "min": 698.4,
          "max": 3434.1,
          "p50": 1002.8,
          "p95": 1612.1
        },
        "error_breakdown": {
          "status_502": 3
        }
      }
    },
    "concurrency": {
      "active_requests": 0,
      "total_requests": 24094,
      "peak_concurrent": 4240,
      "global_limit": 15000,
      "per_domain_limit": 5,
      "slow_domains_count": 878,
      "tracked_domains": 2016,
      "utilization": "0.0%"
    },
    "rate_limiter": {
      "domains_tracked": 858,
      "slow_domains_count": 0,
      "total_requests": 18148,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 858,
      "states": {
        "closed": 857,
        "open": 0,
        "half_open": 1
      },
      "total_blocked": 0,
      "total_opened": 1,
      "config": {
        "failure_threshold": 12,
        "recovery_timeout": 30,
        "half_open_max_tests": 3
      }
    }
  },
  "last_errors": [
    {
      "cnpj": "45018369",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88669
    },
    {
      "cnpj": "03053407",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88631
    },
    {
      "cnpj": "01487757",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88592
    },
    {
      "cnpj": "06939486",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88556
    },
    {
      "cnpj": "52882562",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88519
    },
    {
      "cnpj": "07284448",
      "url": "null",
      "error": "TimeoutError: Timeout aguardando slot de domínio ",
      "time": 1771595219.88471
    }
  ],
  "instances": [
    {
      "id": 0,
      "status": "completed",
      "processed": 200,
      "success": 99,
      "errors": 101,
      "throughput_per_min": 14.3
    },
    {
      "id": 1,
      "status": "completed",
      "processed": 200,
      "success": 100,
      "errors": 100,
      "throughput_per_min": 14.3
    },
    {
      "id": 2,
      "status": "completed",
      "processed": 200,
      "success": 102,
      "errors": 98,
      "throughput_per_min": 14.3
    },
    {
      "id": 3,
      "status": "completed",
      "processed": 200,
      "success": 108,
      "errors": 92,
      "throughput_per_min": 14.3
    },
    {
      "id": 4,
      "status": "completed",
      "processed": 200,
      "success": 87,
      "errors": 113,
      "throughput_per_min": 14.3
    },
    {
      "id": 5,
      "status": "completed",
      "processed": 200,
      "success": 99,
      "errors": 101,
      "throughput_per_min": 14.3
    },
    {
      "id": 6,
      "status": "completed",
      "processed": 200,
      "success": 116,
      "errors": 84,
      "throughput_per_min": 14.3
    },
    {
      "id": 7,
      "status": "completed",
      "processed": 200,
      "success": 112,
      "errors": 88,
      "throughput_per_min": 14.3
    },
    {
      "id": 8,
      "status": "completed",
      "processed": 200,
      "success": 98,
      "errors": 102,
      "throughput_per_min": 14.3
    },
    {
      "id": 9,
      "status": "completed",
      "processed": 200,
      "success": 82,
      "errors": 118,
      "throughput_per_min": 14.3
    }
  ]
}

---

## Run 8 — Diagnóstico de empty_content (com main_page_fail_reasons)

**Data**: 2026-02-19
**Batch**: b32c242c
**Config**: 2000 empresas, 10 instâncias, 400 workers/inst (4000 total)
**Mudanças**: Implementação de `main_page_fail_reasons` para diagnosticar causas do `empty_content`:
- `cffi_scrape_safe` agora registra `last_error` detalhado (proxy_timeout, http_4xx, ssl_error, etc.)
- `_do_scrape` diferencia proxy failures reais de Soft 404 / Cloudflare
- `_try_reuse_analyzer_html` e `_scrape_main_page` retornam motivo de falha
- `ScrapeResult.main_page_fail_reason` propagado até o batch status

### Resultados

| Métrica | Valor |
|---|---|
| Duração | 13.6 min (814s) |
| Throughput | **147.4/min** |
| Success Rate | **50.8%** (1017/2000) |
| **Success excl empty_content** | **97.0%** (1017/1048) |
| Errors | 983 (empty_content: 952, timeout: 31) |
| Subpage Success | **86.5%** (8698/10056) |
| Pages/company | 9.6 |
| Proxy Success | 44.4% (9791/22060) |
| Circuit Breakers | 0 |

### Main Page Fail Reasons (952 falhas)

| Motivo | Count | % |
|---|---|---|
| **probe_unreachable** | 624 | **65.5%** |
| scrape_proxy_fail | 249 | 26.2% |
| scrape_error | 67 | 7.0% |
| concurrency_timeout | 12 | 1.3% |

### Análise

1. **97% success excl empty_content** — lógica de scraping está sólida
2. **probe_unreachable é o problema #1 (65.5%)** — 624 sites falharam no estágio de probe
   - Precisa investigar: são sites genuinamente fora do ar ou o probe está falhando por proxy/timeout?
3. **scrape_proxy_fail (26.2%)** — falhas de proxy na main page, precisa detalhar (timeout vs connection vs HTTP error)
4. **scrape_error (7%)** — erros genéricos no scrape
5. **Subpage success 86.5%** — bom, melhorou em relação ao run anterior
6. **Proxy success 44.4%** — estável em relação ao run anterior

### Próximos passos
- Detalhar `probe_unreachable`: adicionar motivo específico da falha do probe
- Detalhar `scrape_proxy_fail`: separar por tipo (proxy_timeout, proxy_connection, http_4xx, etc.)
- Investigar se `probe_unreachable` são sites sem website ou falha de infra

### JSON completo

```json
{
  "batch_id": "b32c242c",
  "status": "completed",
  "total": 2000,
  "processed": 2000,
  "success_count": 1017,
  "error_count": 983,
  "success_rate_pct": 50.8,
  "throughput_per_min": 147.4,
  "elapsed_seconds": 814.0,
  "error_breakdown": {"empty_content": 952, "timeout": 31},
  "pages_per_company_avg": 9.6,
  "subpage_pipeline": {
    "main_page_failures": 952,
    "main_page_fail_reasons": {
      "probe_unreachable": 624,
      "scrape_proxy_fail": 249,
      "scrape_error": 67,
      "concurrency_timeout": 12
    },
    "subpages_attempted": 10056,
    "subpages_ok": 8698,
    "subpage_success_rate_pct": 86.5
  },
  "infrastructure": {
    "proxy_pool": {
      "total_proxies": 2500,
      "active_proxies": 2494,
      "success_rate": "44.4%",
      "per_proxy_analysis": {
        "avg_pct": 44.1,
        "std_dev_pct": 18.2,
        "verdict": "MODERADA"
      }
    },
    "circuit_breaker": {
      "open_circuits": 0
    }
  }
}
```


run 
{
  "batch_id": "d5c83504",
  "status": "running",
  "total": 1000,
  "processed": 816,
  "success_count": 354,
  "error_count": 462,
  "success_rate_pct": 43.4,
  "remaining": 184,
  "in_progress": 184,
  "peak_in_progress": 1000,
  "throughput_per_min": 116.1,
  "eta_minutes": 1.6,
  "elapsed_seconds": 421.7,
  "flushes_done": 0,
  "buffer_size": 816,
  "processing_time_ms": {
    "avg": 205131.1,
    "min": 2437,
    "max": 360610.3,
    "p50": 178366.8,
    "p60": 236323.6,
    "p70": 269311.1,
    "p80": 282165.1,
    "p90": 326339.3,
    "p95": 327309,
    "p99": 354400
  },
  "error_breakdown": {
    "empty_content": 462
  },
  "pages_per_company_avg": 7.3,
  "total_retries": 0,
  "subpage_pipeline": {
    "links_in_html_total": 7997,
    "links_after_filter": 7997,
    "links_selected": 4171,
    "links_per_company_avg": 9.8,
    "selected_per_company_avg": 5.1,
    "zero_links_companies": 48,
    "zero_links_pct": 5.9,
    "main_page_failures": 462,
    "main_page_fail_reasons": {
      "probe:timeout": 350,
      "proxy:timeout": 48,
      "scrape:error": 30,
      "probe:ssl": 12,
      "proxy:empty_response": 11,
      "proxy:http_5xx": 7,
      "proxy:connection": 4
    },
    "subpages_attempted": 2520,
    "subpages_ok": 2239,
    "subpages_failed": 281,
    "subpage_success_rate_pct": 88.8,
    "subpage_error_breakdown": {
      "scrape_fail": 128,
      "timeout_slot": 5
    }
  },
  "infrastructure": {
    "proxy_pool": {
      "loaded": true,
      "total_proxies": 2500,
      "active_proxies": 2500,
      "health_checked": true,
      "proxy_allocations": 16069,
      "total_outcomes": 9538,
      "successful": 4427,
      "failed": 5111,
      "success_rate": "46.4%",
      "per_proxy_analysis": {
        "proxies_analyzed": 2280,
        "proxies_used": 2500,
        "proxies_unused": 0,
        "success_rate_distribution": {
          "avg_pct": 47.3,
          "std_dev_pct": 25.5,
          "min_pct": 0,
          "max_pct": 100,
          "p10": 16.7,
          "p25": 33.3,
          "p50": 50,
          "p75": 66.7,
          "p90": 75
        },
        "buckets": {
          "90_100_pct": 125,
          "70_90_pct": 316,
          "50_70_pct": 773,
          "30_50_pct": 553,
          "10_30_pct": 314,
          "0_10_pct": 199
        },
        "verdict": "DISPERSA — grande variação (std=26%). Alguns proxies são muito piores que outros. Filtrar proxies ruins pode ajudar.",
        "worst_5": [
          {
            "proxy_id": "197.223:6462",
            "requests": 7,
            "outcomes": 4,
            "successes": 0,
            "failures": 4,
            "success_rate_pct": 0
          },
          {
            "proxy_id": "252.186:6454",
            "requests": 7,
            "outcomes": 3,
            "successes": 0,
            "failures": 3,
            "success_rate_pct": 0
          },
          {
            "proxy_id": ".92.137:6071",
            "requests": 7,
            "outcomes": 3,
            "successes": 0,
            "failures": 3,
            "success_rate_pct": 0
          },
          {
            "proxy_id": "3.91.81:6514",
            "requests": 7,
            "outcomes": 5,
            "successes": 0,
            "failures": 5,
            "success_rate_pct": 0
          },
          {
            "proxy_id": "240.136:7172",
            "requests": 7,
            "outcomes": 5,
            "successes": 0,
            "failures": 5,
            "success_rate_pct": 0
          }
        ],
        "best_5": [
          {
            "proxy_id": "8.67.36:6968",
            "requests": 6,
            "outcomes": 3,
            "successes": 3,
            "failures": 0,
            "success_rate_pct": 100
          },
          {
            "proxy_id": "252.129:6397",
            "requests": 6,
            "outcomes": 4,
            "successes": 4,
            "failures": 0,
            "success_rate_pct": 100
          },
          {
            "proxy_id": "8.67.16:6948",
            "requests": 6,
            "outcomes": 4,
            "successes": 4,
            "failures": 0,
            "success_rate_pct": 100
          },
          {
            "proxy_id": ".171.69:6037",
            "requests": 6,
            "outcomes": 5,
            "successes": 5,
            "failures": 0,
            "success_rate_pct": 100
          },
          {
            "proxy_id": ".92.161:6095",
            "requests": 6,
            "outcomes": 5,
            "successes": 5,
            "failures": 0,
            "success_rate_pct": 100
          }
        ]
      },
      "health_check": {
        "total_tested": 2500,
        "healthy": 2500,
        "dead": 0,
        "healthy_pct": 100,
        "pool_active": 2500,
        "check_time_ms": 54292,
        "latency_ms": {
          "avg": 1070.5,
          "min": 685,
          "max": 2842.6,
          "p50": 1002.8,
          "p95": 1584.2
        },
        "error_breakdown": {

        }
      }
    },
    "concurrency": {
      "active_requests": 481,
      "total_requests": 10706,
      "peak_concurrent": 1868,
      "global_limit": 15000,
      "per_domain_limit": 5,
      "slow_domains_count": 304,
      "tracked_domains": 1054,
      "utilization": "3.2%"
    },
    "rate_limiter": {
      "domains_tracked": 431,
      "slow_domains_count": 0,
      "total_requests": 8540,
      "throttled_requests": 0,
      "throttle_rate": "0.0%",
      "config": {
        "default_rpm": 300,
        "burst_size": 60,
        "slow_domain_rpm": 60
      }
    },
    "circuit_breaker": {
      "domains_tracked": 431,
      "states": {
        "closed": 431,
        "open": 0,
        "half_open": 0
      },
      "total_blocked": 0,
      "total_opened": 0,
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
      "status": "running",
      "processed": 81,
      "success": 34,
      "errors": 47,
      "throughput_per_min": 13.3
    },
    {
      "id": 1,
      "status": "running",
      "processed": 78,
      "success": 37,
      "errors": 41,
      "throughput_per_min": 12.8
    },
    {
      "id": 2,
      "status": "running",
      "processed": 80,
      "success": 37,
      "errors": 43,
      "throughput_per_min": 13.2
    },
    {
      "id": 3,
      "status": "running",
      "processed": 84,
      "success": 30,
      "errors": 54,
      "throughput_per_min": 13.8
    },
    {
      "id": 4,
      "status": "running",
      "processed": 82,
      "success": 38,
      "errors": 44,
      "throughput_per_min": 13.5
    },
    {
      "id": 5,
      "status": "running",
      "processed": 76,
      "success": 27,
      "errors": 49,
      "throughput_per_min": 12.5
    },
    {
      "id": 6,
      "status": "running",
      "processed": 78,
      "success": 35,
      "errors": 43,
      "throughput_per_min": 12.8
    },
    {
      "id": 7,
      "status": "running",
      "processed": 87,
      "success": 47,
      "errors": 40,
      "throughput_per_min": 14.3
    },
    {
      "id": 8,
      "status": "running",
      "processed": 78,
      "success": 35,
      "errors": 43,
      "throughput_per_min": 12.8
    },
    {
      "id": 9,
      "status": "running",
      "processed": 92,
      "success": 34,
      "errors": 58,
      "throughput_per_min": 15.1
    }
  ]
}