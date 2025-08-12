#!/usr/bin/env python3
"""
Simple runner script for RunPod Monitor
"""

import sys
import os

# Add the package directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'runpod_monitor'))

from main import main

if __name__ == "__main__":
    main()