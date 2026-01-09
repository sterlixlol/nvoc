"""
NVOC - Narrative Feedback System

Provides human-feeling status messages during operations.
Messages rotate and avoid repetition.
"""

import random
from typing import List, Optional

# Message pools for different operation types
NARRATIVES = {
    "apply": [
        "Settings locked in.",
        "Configuration committed.",
        "Changes applied successfully.",
        "Parameters updated.",
        "Settings confirmed.",
    ],
    "stability": [
        "Stability holding steady.",
        "System responding as expected.",
        "Performance metrics nominal.",
        "Running smoothly.",
        "All systems stable.",
    ],
    "power": [
        "Power profile active.",
        "Power headroom looking good.",
        "Efficiency parameters set.",
        "Power delivery stable.",
    ],
    "thermal": [
        "Thermals under control.",
        "Cooling responding well.",
        "Temperature headroom healthy.",
        "Heat management stable.",
    ],
    "clocks": [
        "Clocks responding as expected.",
        "Frequency targets set.",
        "Boost behavior configured.",
        "Clock offsets applied.",
    ],
    "profile": [
        "Profile loaded.",
        "Configuration restored.",
        "Preset applied.",
        "Settings imported.",
    ],
    "test": [
        "Stress test progressing.",
        "Workload sustaining.",
        "GPU under load.",
        "Benchmark running.",
    ],
    "complete": [
        "Test completed successfully.",
        "Benchmark finished.",
        "Stress test concluded.",
        "Workload completed.",
    ],
}

# Track recently used messages to avoid repetition
_recent_messages: List[str] = []
_max_recent = 5


def get_narrative(category: str) -> Optional[str]:
    """Get a random narrative message for the given category.
    
    Avoids repeating recently used messages.
    Returns None if category not found.
    """
    global _recent_messages
    
    pool = NARRATIVES.get(category)
    if not pool:
        return None
    
    # Filter out recently used messages
    available = [msg for msg in pool if msg not in _recent_messages]
    
    # If all messages were recent, reset tracking
    if not available:
        _recent_messages = []
        available = pool.copy()
    
    # Pick random message
    message = random.choice(available)
    
    # Track as recently used
    _recent_messages.append(message)
    if len(_recent_messages) > _max_recent:
        _recent_messages.pop(0)
    
    return message
