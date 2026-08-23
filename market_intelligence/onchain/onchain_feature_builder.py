def assert_cutoff(metric_times,baseline_times):
    return bool((metric_times<=baseline_times).all())
