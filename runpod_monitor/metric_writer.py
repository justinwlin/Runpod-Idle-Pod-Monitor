"""
Event-based metric writer with hook support.
Allows injection of custom functions into the write pipeline.
"""

import json
import os
from typing import Dict, Any, Callable, List, Optional


class MetricWriter:
    """
    Event-based metric writer that supports pre and post write hooks.
    This allows for easy injection of additional functionality without
    modifying the core writing logic.
    """
    
    def __init__(self):
        """Initialize the metric writer with empty hook lists."""
        self.on_start_hooks: List[Callable] = []
        self.pre_write_hooks: List[Callable] = []
        self.post_write_hooks: List[Callable] = []
        self.write_count = 0  # Track number of writes for hooks that need it
        self.started = False
        
    def add_on_start_hook(self, func: Callable[[], None]) -> None:
        """
        Add a function to execute on start.
        
        On-start hooks are called once when start() is called.
        They can be used for initialization, data migration, etc.
        
        Args:
            func: Function that takes no arguments and returns None
        """
        self.on_start_hooks.append(func)
        print(f"✅ Added on-start hook: {func.__name__}")
        
    def start(self) -> None:
        """
        Execute all on-start hooks.
        This should be called once before using the writer.
        """
        if self.started:
            print("⚠️ MetricWriter already started")
            return
            
        print("🚀 Starting MetricWriter...")
        for hook in self.on_start_hooks:
            try:
                print(f"  Running on-start hook: {hook.__name__}")
                hook()
            except Exception as e:
                print(f"❌ Error in on-start hook {hook.__name__}: {e}")
        
        self.started = True
        print("✅ MetricWriter started")
        
    def add_pre_write_hook(self, func: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """
        Add a function to execute before writing the metric.
        
        Pre-write hooks receive the metric and can transform it.
        They must return the (possibly modified) metric.
        
        Args:
            func: Function that takes a metric dict and returns a metric dict
        """
        self.pre_write_hooks.append(func)
        print(f"✅ Added pre-write hook: {func.__name__}")
        
    def add_post_write_hook(self, func: Callable[[Dict[str, Any], str], None]) -> None:
        """
        Add a function to execute after writing the metric.
        
        Post-write hooks receive the metric and file path.
        They can trigger additional actions but don't modify the metric.
        
        Args:
            func: Function that takes (metric_dict, file_path) and returns None
        """
        self.post_write_hooks.append(func)
        print(f"✅ Added post-write hook: {func.__name__}")
        
    def remove_hook(self, func: Callable) -> bool:
        """
        Remove a hook function from both pre and post write lists.
        
        Args:
            func: The function to remove
            
        Returns:
            True if the hook was found and removed, False otherwise
        """
        removed = False
        if func in self.pre_write_hooks:
            self.pre_write_hooks.remove(func)
            removed = True
        if func in self.post_write_hooks:
            self.post_write_hooks.remove(func)
            removed = True
        
        if removed:
            print(f"✅ Removed hook: {func.__name__}")
        return removed
        
    def clear_hooks(self) -> None:
        """Clear all hooks (useful for testing or reconfiguration)."""
        self.pre_write_hooks.clear()
        self.post_write_hooks.clear()
        print("🧹 Cleared all hooks")
        
    def write_metric(self, metric_point: Dict[str, Any], file_path: str) -> bool:
        """
        Write a metric with all registered hooks.
        
        Args:
            metric_point: The metric dictionary to write
            file_path: Path to the JSONL file
            
        Returns:
            True if write was successful, False otherwise
        """
        try:
            # Execute pre-write hooks (can transform the metric)
            for hook in self.pre_write_hooks:
                try:
                    metric_point = hook(metric_point)
                    if metric_point is None:
                        print(f"⚠️ Pre-write hook {hook.__name__} returned None, skipping write")
                        return False
                except Exception as e:
                    print(f"❌ Error in pre-write hook {hook.__name__}: {e}")
                    # Continue with other hooks but log the error
            
            # Perform the actual write
            with open(file_path, 'a') as f:
                f.write(json.dumps(metric_point) + '\n')
            
            self.write_count += 1
            
            # Execute post-write hooks (for additional actions)
            for hook in self.post_write_hooks:
                try:
                    hook(metric_point, file_path)
                except Exception as e:
                    print(f"❌ Error in post-write hook {hook.__name__}: {e}")
                    # Continue with other hooks but log the error
            
            return True
            
        except IOError as e:
            print(f"❌ Error writing metric to file: {e}")
            return False
            
    def get_hook_info(self) -> Dict[str, List[str]]:
        """
        Get information about registered hooks.
        
        Returns:
            Dictionary with lists of hook function names
        """
        return {
            "pre_write_hooks": [func.__name__ for func in self.pre_write_hooks],
            "post_write_hooks": [func.__name__ for func in self.post_write_hooks],
            "total_writes": self.write_count
        }