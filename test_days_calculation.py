#!/usr/bin/env python
"""
Test script to verify the days remaining calculation
"""
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from datetime import datetime, timedelta
from django.utils import timezone
from dateutil.parser import parse

def test_days_calculation():
    """Test the days calculation logic from the API response"""
    
    # Data from the API response
    trial_started_str = "2026-02-26T00:48:19.382183+00:00"
    trial_ends_str = "2026-03-12T00:48:19.382188+00:00" 
    
    # Parse the dates
    trial_started = parse(trial_started_str)
    trial_ends = parse(trial_ends_str)
    
    print(f"Trial started: {trial_started}")
    print(f"Trial ends: {trial_ends}")
    
    # The current date from context is Feb 26, 2026
    # Let's test different times during that day
    test_times = [
        "2026-02-26T00:00:00+00:00",  # Midnight
        "2026-02-26T00:48:19+00:00",  # Exact start time
        "2026-02-26T12:00:00+00:00",  # Noon  
        "2026-02-26T23:59:59+00:00",  # End of day
    ]
    
    for test_time_str in test_times:
        test_now = parse(test_time_str)
        
        # Calculate using the same logic as the code
        days_remaining = max(0, (trial_ends - test_now).days)
        days_used = (test_now - trial_started).days if test_now > trial_started else 0
        
        print(f"\nAt {test_time_str}:")
        print(f"  Days remaining: {days_remaining}")
        print(f"  Days used: {days_used}")
        print(f"  Time difference: {trial_ends - test_now}")
        
    # Also test the total duration
    total_duration = trial_ends - trial_started
    print(f"\nTotal trial duration: {total_duration} = {total_duration.days} days")

if __name__ == "__main__":
    test_days_calculation()