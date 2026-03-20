#!/usr/bin/env python3
"""
🏦 Broker Selection System - Tradovate Only
Trade Account Connector - Simplified for Tradovate integration
"""

import tkinter as tk
from tkinter import ttk, messagebox, StringVar, BooleanVar
import logging
from typing import Dict, Callable, Optional
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class BrokerConfig:
    """
    Configuration management for Tradovate broker
    """
    
    BROKERS = {
        'tradovate': {
            'name': 'Tradovate',
            'display_name': 'Tradovate (Web-based)',
            'type': 'web',
            'connection_class': 'TradovateAccount',
            'description': 'Web-based futures trading platform',
            'features': [
                '✅ Web-based platform (no installation)',
                '✅ No additional software required',
                '✅ $0.85 per contract commission',
                '✅ Free platform and data feeds',
                '✅ Easy setup and familiar interface',
                '✅ Current stable integration'
            ],
            'requirements': [
                'Tradovate account credentials',
                'Internet connection',
                'Chrome browser'
            ],
            'costs': {
                'platform': 'FREE',
                'data': 'FREE',
                'commission': '$0.85/contract',
                'monthly': '$0'
            },
            'setup_complexity': 'Easy',
            'recommended_for': 'All traders',
            'credentials': ['username', 'password']
        }
    }
    
    @classmethod
    def get_broker_config(cls, broker_type: str) -> Dict:
        """Get configuration for specific broker"""
        return cls.BROKERS.get(broker_type, {})
    
    @classmethod
    def list_brokers(cls) -> Dict[str, str]:
        """List all available brokers"""
        return {k: v['display_name'] for k, v in cls.BROKERS.items()}

class BrokerSelectionSection:
    """
    Simplified broker selection - Tradovate only
    """
    
    def __init__(self, parent, on_selection_change: Optional[Callable] = None):
        self.parent = parent
        self.on_selection_change = on_selection_change
        self.confirmed_broker = 'tradovate'  # Default to Tradovate
        
        # Create section frame
        self.section_frame = ttk.LabelFrame(parent, text="Broker Platform", padding=(10, 10))
        
        # Simple label since only Tradovate is supported
        self.broker_label = ttk.Label(
            self.section_frame, 
            text="Using Tradovate (Web-based futures trading)",
            font=("Segoe UI", 10)
        )
        self.broker_label.pack(anchor="w", pady=(0, 5))
        
        # Features display
        features_text = "✅ No installation required • ✅ $0.85/contract • ✅ Free platform & data"
        self.features_label = ttk.Label(
            self.section_frame,
            text=features_text,
            font=("Segoe UI", 8),
            foreground="#666666"
        )
        self.features_label.pack(anchor="w")
    
    def pack(self, **kwargs):
        """Pack the section frame"""
        self.section_frame.pack(**kwargs)
    
    def get_selected_broker(self) -> str:
        """Get selected broker"""
        return 'tradovate'

class BrokerCredentialsDialog:
    """
    Credentials dialog - simplified for Tradovate only
    """
    
    def __init__(self, parent, broker_id: str = "tradovate"):
        self.parent = parent
        self.broker_id = broker_id
        self.result = None
        self.credentials = {}
        
    def show(self):
        """Show credentials dialog - for Tradovate, return empty (credentials handled by combine cards)"""
        # For Tradovate, credentials are handled in the combine cards
        return "ok", {}

class BrokerSelectionView:
    """
    Complete broker selection view - simplified for Tradovate
    """
    
    def __init__(self, master, on_confirm: Optional[Callable] = None):
        self.master = master
        self.on_confirm = on_confirm
        self.selected_broker = StringVar(value="tradovate")
        
        # Create main window
        self.root = tk.Toplevel(master)
        self.root.title("Broker Selection")
        self.root.geometry("500x300")
        self.root.resizable(False, False)
        
        # Center window
        self.root.transient(master)
        self.root.grab_set()
        
        self._create_widgets()
        
    def _create_widgets(self):
        """Create dialog widgets"""
        # Header
        header_frame = ttk.Frame(self.root, padding=(20, 20, 20, 10))
        header_frame.pack(fill="x")
        
        header_label = ttk.Label(
            header_frame,
            text="Trading Platform Selection",
            font=("Segoe UI", 14, "bold")
        )
        header_label.pack()
        
        # Content
        content_frame = ttk.Frame(self.root, padding=(20, 0, 20, 20))
        content_frame.pack(fill="both", expand=True)
        
        # Tradovate info
        info_text = """🏦 Tradovate Platform

✅ Web-based futures trading platform
✅ No installation required  
✅ $0.85 per contract commission
✅ Free platform and data feeds
✅ Stable, proven integration

This app is currently optimized for Tradovate trading.
Enter your Tradovate credentials in the combine sections to begin trading."""
        
        info_label = ttk.Label(
            content_frame,
            text=info_text,
            font=("Segoe UI", 10),
            justify="left"
        )
        info_label.pack(pady=(0, 20))
        
        # Buttons
        button_frame = ttk.Frame(content_frame)
        button_frame.pack(fill="x")
        
        ttk.Button(
            button_frame,
            text="Continue with Tradovate",
            command=self._confirm_selection
        ).pack(side="right", padx=(10, 0))
        
        ttk.Button(
            button_frame,
            text="Cancel",
            command=self._cancel
        ).pack(side="right")
    
    def _confirm_selection(self):
        """Confirm broker selection"""
        if self.on_confirm:
            self.on_confirm("tradovate")
        self.root.destroy()
        
    def _cancel(self):
        """Cancel selection"""
        self.root.destroy()

# For backwards compatibility
class BrokerCredentialsDialog:
    def __init__(self, parent, broker_id="tradovate"):
        pass
    
    def show(self):
        return "ok", {}
