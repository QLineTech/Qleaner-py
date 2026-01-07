#!/usr/bin/env python3
"""
Q-Cleaner Web Panel for macOS
A web-based cache and temp file cleaner with system monitoring
"""

import os
import shutil
import subprocess
import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from flask import Flask, render_template, jsonify, request, send_from_directory
import webbrowser
import socket

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. System monitoring will be limited.")
    print("Install with: pip install psutil")

app = Flask(__name__)

# Global state
scan_results = []
scan_in_progress = False
scan_complete = False
scan_progress = {
    "current": 0,
    "total": 0,
    "percent": 0,
    "current_location": "",
    "found_count": 0,
    "total_size": 0
}


@dataclass
class CacheLocation:
    id: str
    path: str
    name: str
    description: str
    category: str
    hint: str
    impact: str
    risk: str
    size: int = 0
    size_human: str = "0B"
    selected: bool = False
    exists: bool = False


@dataclass
class LeftoverItem:
    """Represents a leftover file/folder from an uninstalled application."""
    id: str
    path: str
    name: str                  # App name (inferred or from receipt)
    bundle_id: str            # e.g., com.example.app
    detection_source: str     # receipts, container, preferences, etc.
    category: str             # Containers, Preferences, LaunchAgents, etc.
    confidence: str           # high, medium, low
    hint: str                 # Description of what this leftover is
    size: int = 0
    size_human: str = "0B"
    selected: bool = False


def get_home() -> str:
    return str(Path.home())


def human_readable_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size_bytes) < 1024.0:
            if unit == 'B':
                return f"{size_bytes} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def get_directory_size(path: str) -> int:
    try:
        result = subprocess.run(
            ['du', '-sk', path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            size_kb = int(result.stdout.split()[0])
            return size_kb * 1024
    except:
        pass
    
    total_size = 0
    try:
        path_obj = Path(path)
        if path_obj.is_file():
            return path_obj.stat().st_size
        for entry in path_obj.rglob('*'):
            try:
                if entry.is_file():
                    total_size += entry.stat().st_size
            except:
                pass
    except:
        pass
    return total_size


# ============================================================================
# LEFTOVER DETECTION SYSTEM
# ============================================================================

# Global state for leftovers
leftover_results = []
leftover_scan_in_progress = False
leftover_scan_complete = False
leftover_scan_progress = {
    "current": 0,
    "total": 0,
    "percent": 0,
    "current_location": "",
    "found_count": 0,
    "total_size": 0
}


def parse_plist_bundle_id(plist_path: str) -> str:
    """Extract CFBundleIdentifier from an Info.plist file."""
    try:
        result = subprocess.run(
            ['defaults', 'read', plist_path, 'CFBundleIdentifier'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return ""


def infer_app_name(bundle_id: str) -> str:
    """Infer a human-readable app name from a bundle identifier."""
    if not bundle_id:
        return "Unknown App"
    
    # Split by dots and take the last meaningful part
    parts = bundle_id.split('.')
    if len(parts) >= 1:
        # Get the last part, capitalize it, and clean up
        name = parts[-1]
        # Convert camelCase or PascalCase to spaces
        import re
        name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
        # Convert dashes/underscores to spaces
        name = name.replace('-', ' ').replace('_', ' ')
        # Capitalize words
        return name.title()
    return bundle_id


def get_installed_bundle_ids() -> set:
    """Get all bundle IDs from currently installed applications."""
    bundle_ids = set()
    
    try:
        # Method 1: Use mdfind to query Spotlight for all applications
        result = subprocess.run(
            ['mdfind', 'kMDItemContentType == "com.apple.application-bundle"'],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0:
            for app_path in result.stdout.strip().split('\n'):
                if app_path and os.path.exists(app_path):
                    plist_path = os.path.join(app_path, 'Contents', 'Info.plist')
                    if os.path.exists(plist_path):
                        bundle_id = parse_plist_bundle_id(plist_path)
                        if bundle_id:
                            bundle_ids.add(bundle_id.lower())
    except:
        pass
    
    # Method 2: Also scan /Applications directly as fallback
    try:
        apps_dir = Path('/Applications')
        for app in apps_dir.glob('*.app'):
            plist_path = app / 'Contents' / 'Info.plist'
            if plist_path.exists():
                bundle_id = parse_plist_bundle_id(str(plist_path))
                if bundle_id:
                    bundle_ids.add(bundle_id.lower())
    except:
        pass
    
    # Method 3: Also check user Applications
    try:
        user_apps = Path.home() / 'Applications'
        if user_apps.exists():
            for app in user_apps.glob('*.app'):
                plist_path = app / 'Contents' / 'Info.plist'
                if plist_path.exists():
                    bundle_id = parse_plist_bundle_id(str(plist_path))
                    if bundle_id:
                        bundle_ids.add(bundle_id.lower())
    except:
        pass
    
    return bundle_ids


def detect_container_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find containers for apps that are no longer installed."""
    orphans = []
    containers_path = Path.home() / 'Library' / 'Containers'
    
    if not containers_path.exists():
        return orphans
    
    try:
        for container in containers_path.iterdir():
            if container.is_dir():
                container_id = container.name.lower()
                if container_id not in installed_ids:
                    size = get_directory_size(str(container))
                    if size > 0:  # Only include non-empty containers
                        orphans.append(LeftoverItem(
                            id=f"container_{container.name}",
                            path=str(container),
                            name=infer_app_name(container.name),
                            bundle_id=container.name,
                            detection_source="container_scan",
                            category="Containers",
                            confidence="high",
                            hint=f"Sandboxed data container for '{infer_app_name(container.name)}'. This app appears to be uninstalled.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
    except:
        pass
    
    return orphans


def detect_group_container_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find group containers for apps that are no longer installed."""
    orphans = []
    group_containers_path = Path.home() / 'Library' / 'Group Containers'
    
    if not group_containers_path.exists():
        return orphans
    
    try:
        for container in group_containers_path.iterdir():
            if container.is_dir():
                # Group containers have format: TEAMID.com.example.group
                container_id = container.name.lower()
                # Extract bundle-like portion after team ID
                parts = container.name.split('.', 1)
                if len(parts) > 1:
                    bundle_portion = parts[1].lower()
                else:
                    bundle_portion = container_id
                
                # Check if any installed app matches this group container
                is_orphan = True
                for installed_id in installed_ids:
                    if installed_id in container_id or bundle_portion in installed_id:
                        is_orphan = False
                        break
                
                if is_orphan:
                    size = get_directory_size(str(container))
                    if size > 0:
                        orphans.append(LeftoverItem(
                            id=f"group_container_{container.name}",
                            path=str(container),
                            name=infer_app_name(container.name),
                            bundle_id=container.name,
                            detection_source="group_container_scan",
                            category="Group Containers",
                            confidence="high",
                            hint=f"Shared data container for '{infer_app_name(container.name)}'. No matching app found.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
    except:
        pass
    
    return orphans


def detect_preference_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find preference files for apps that are no longer installed."""
    orphans = []
    prefs_path = Path.home() / 'Library' / 'Preferences'
    
    if not prefs_path.exists():
        return orphans
    
    # Known system/Apple preferences to skip
    skip_prefixes = ['com.apple.', 'org.python.', 'com.github.', 'loginwindow',
                     'pbs', 'systemsoundserverd', 'ContextStoreAgent', 'NSGlobalDomain']
    
    try:
        for pref_file in prefs_path.glob('*.plist'):
            if pref_file.is_file():
                pref_name = pref_file.stem.lower()
                
                # Skip known system preferences
                if any(pref_name.startswith(prefix.lower()) for prefix in skip_prefixes):
                    continue
                
                # Check if this preference belongs to an installed app
                is_orphan = True
                for installed_id in installed_ids:
                    if pref_name == installed_id or pref_name.startswith(installed_id):
                        is_orphan = False
                        break
                    if installed_id in pref_name:
                        is_orphan = False
                        break
                
                if is_orphan:
                    size = pref_file.stat().st_size
                    if size > 0:
                        orphans.append(LeftoverItem(
                            id=f"pref_{pref_file.stem}",
                            path=str(pref_file),
                            name=infer_app_name(pref_file.stem),
                            bundle_id=pref_file.stem,
                            detection_source="preferences_scan",
                            category="Preferences",
                            confidence="medium",
                            hint=f"Preference file for '{infer_app_name(pref_file.stem)}'. No matching app installed.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
    except:
        pass
    
    return orphans


def detect_app_support_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find Application Support folders for apps that are no longer installed."""
    orphans = []
    app_support_path = Path.home() / 'Library' / 'Application Support'
    
    if not app_support_path.exists():
        return orphans
    
    # Known system/essential folders to skip
    skip_folders = ['AddressBook', 'AppStore', 'CallHistoryDB', 'CloudDocs',
                    'CrashReporter', 'Dock', 'FileProvider', 'iCloud', 'icdd',
                    'Knowledge', 'MobileSync', 'NotificationCenter', 'Quick Look',
                    'Spotlight', 'com.apple.', 'Apple', 'SyncServices', 'CoreData']
    
    try:
        for folder in app_support_path.iterdir():
            if folder.is_dir():
                folder_name = folder.name.lower()
                
                # Skip known system folders
                if any(folder_name.startswith(skip.lower()) or folder_name == skip.lower() 
                       for skip in skip_folders):
                    continue
                
                # Check if this folder belongs to an installed app
                is_orphan = True
                for installed_id in installed_ids:
                    # Match by last portion of bundle ID or folder name
                    installed_parts = installed_id.split('.')
                    if folder_name in installed_id or installed_id in folder_name:
                        is_orphan = False
                        break
                    if any(part.lower() == folder_name for part in installed_parts):
                        is_orphan = False
                        break
                
                if is_orphan:
                    size = get_directory_size(str(folder))
                    if size > 1024:  # Only include folders > 1KB
                        orphans.append(LeftoverItem(
                            id=f"appsupport_{folder.name}",
                            path=str(folder),
                            name=folder.name,
                            bundle_id=f"*.{folder.name}",
                            detection_source="app_support_scan",
                            category="Application Support",
                            confidence="medium",
                            hint=f"Application Support folder for '{folder.name}'. No matching app installed.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
    except:
        pass
    
    return orphans


def detect_launch_agent_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find Launch Agents for apps that are no longer installed."""
    orphans = []
    
    # Check both user and system launch agents
    launch_agent_paths = [
        Path.home() / 'Library' / 'LaunchAgents',
        Path('/Library/LaunchAgents'),
    ]
    
    # Known system launch agents to skip
    skip_prefixes = ['com.apple.', 'com.openssh', 'bootcamp', 'org.gpgtools']
    
    for launch_path in launch_agent_paths:
        if not launch_path.exists():
            continue
        
        try:
            for plist_file in launch_path.glob('*.plist'):
                if plist_file.is_file():
                    plist_name = plist_file.stem.lower()
                    
                    # Skip known system agents
                    if any(plist_name.startswith(prefix.lower()) for prefix in skip_prefixes):
                        continue
                    
                    # Check if this launch agent belongs to an installed app
                    is_orphan = True
                    for installed_id in installed_ids:
                        if plist_name == installed_id or installed_id in plist_name:
                            is_orphan = False
                            break
                        if plist_name in installed_id:
                            is_orphan = False
                            break
                    
                    if is_orphan:
                        size = plist_file.stat().st_size
                        orphans.append(LeftoverItem(
                            id=f"launchagent_{plist_file.stem}",
                            path=str(plist_file),
                            name=infer_app_name(plist_file.stem),
                            bundle_id=plist_file.stem,
                            detection_source="launch_agent_scan",
                            category="Launch Agents",
                            confidence="high",
                            hint=f"Background agent for '{infer_app_name(plist_file.stem)}'. The associated app is not installed.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
        except:
            pass
    
    return orphans


def detect_cache_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find cache folders for apps that are no longer installed."""
    orphans = []
    caches_path = Path.home() / 'Library' / 'Caches'
    
    if not caches_path.exists():
        return orphans
    
    # Known system caches to skip
    skip_prefixes = ['com.apple.', 'CloudKit', 'GeoServices', 'PassKit',
                     'com.crashlytics', 'google', 'org.swift']
    
    try:
        for cache_folder in caches_path.iterdir():
            if cache_folder.is_dir():
                cache_name = cache_folder.name.lower()
                
                # Skip known system caches
                if any(cache_name.startswith(prefix.lower()) for prefix in skip_prefixes):
                    continue
                
                # Check if this cache belongs to an installed app
                is_orphan = True
                for installed_id in installed_ids:
                    if cache_name == installed_id or installed_id in cache_name:
                        is_orphan = False
                        break
                    if cache_name in installed_id:
                        is_orphan = False
                        break
                
                if is_orphan:
                    size = get_directory_size(str(cache_folder))
                    if size > 10240:  # Only include caches > 10KB
                        orphans.append(LeftoverItem(
                            id=f"cache_{cache_folder.name}",
                            path=str(cache_folder),
                            name=infer_app_name(cache_folder.name),
                            bundle_id=cache_folder.name,
                            detection_source="cache_scan",
                            category="Caches",
                            confidence="medium",
                            hint=f"Cache folder for '{infer_app_name(cache_folder.name)}'. No matching app installed.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True
                        ))
    except:
        pass
    
    return orphans


def detect_logs_orphans(installed_ids: set) -> List[LeftoverItem]:
    """Find log folders for apps that are no longer installed."""
    orphans = []
    logs_path = Path.home() / 'Library' / 'Logs'
    
    if not logs_path.exists():
        return orphans
    
    # Known system logs to skip
    skip_folders = ['DiagnosticReports', 'com.apple.', 'CoreSimulator', 'Homebrew']
    
    try:
        for log_folder in logs_path.iterdir():
            if log_folder.is_dir():
                log_name = log_folder.name.lower()
                
                # Skip known system logs
                if any(log_name.startswith(skip.lower()) or log_name == skip.lower()
                       for skip in skip_folders):
                    continue
                
                # Check if this log folder belongs to an installed app
                is_orphan = True
                for installed_id in installed_ids:
                    if log_name in installed_id or installed_id in log_name:
                        is_orphan = False
                        break
                    installed_parts = installed_id.split('.')
                    if any(part.lower() == log_name for part in installed_parts):
                        is_orphan = False
                        break
                
                if is_orphan:
                    size = get_directory_size(str(log_folder))
                    if size > 1024:  # Only include logs > 1KB
                        orphans.append(LeftoverItem(
                            id=f"logs_{log_folder.name}",
                            path=str(log_folder),
                            name=log_folder.name,
                            bundle_id=f"*.{log_folder.name}",
                            detection_source="logs_scan",
                            category="Logs",
                            confidence="low",
                            hint=f"Log folder for '{log_folder.name}'. No matching app installed. Low confidence - verify before removing.",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=False  # Don't auto-select low confidence items
                        ))
    except:
        pass
    
    return orphans


def get_cache_locations() -> List[CacheLocation]:
    home = get_home()
    
    locations = [
        CacheLocation(
            id="user_caches",
            path=f"{home}/Library/Caches",
            name="User Application Caches",
            description="Cache files from all your applications",
            category="System",
            hint="This folder contains cached data from all applications you use. Apps store temporary files here to speed up loading times.",
            impact="Apps will need to re-download or regenerate their cached data. Generally safe.",
            risk="low"
        ),
        CacheLocation(
            id="system_caches",
            path="/Library/Caches",
            name="System Application Caches",
            description="System-wide application caches",
            category="System",
            hint="Contains cached data for system-level applications and services.",
            impact="System apps will regenerate caches as needed. May require admin password.",
            risk="medium"
        ),
        CacheLocation(
            id="xcode_derived",
            path=f"{home}/Library/Developer/Xcode/DerivedData",
            name="Xcode DerivedData",
            description="Xcode build intermediates and indexes",
            category="Developer",
            hint="Contains all build products, indexes, and logs from Xcode projects.",
            impact="Next build will take longer as Xcode rebuilds everything from scratch.",
            risk="low"
        ),
        CacheLocation(
            id="xcode_archives",
            path=f"{home}/Library/Developer/Xcode/Archives",
            name="Xcode Archives",
            description="App Store submission archives",
            category="Developer",
            hint="Contains archived builds used for App Store submissions.",
            impact="⚠️ You will lose the ability to symbolicate crash reports from these builds.",
            risk="high"
        ),
        CacheLocation(
            id="xcode_device_support",
            path=f"{home}/Library/Developer/Xcode/iOS DeviceSupport",
            name="iOS Device Support",
            description="Debug symbols for iOS devices",
            category="Developer",
            hint="Contains debug symbols for each iOS version you've connected. Often 2-5GB each!",
            impact="Xcode will re-download symbols when you next connect a device.",
            risk="low"
        ),
        CacheLocation(
            id="simulator_devices",
            path=f"{home}/Library/Developer/CoreSimulator/Devices",
            name="iOS Simulator Devices",
            description="All iOS Simulator instances and data",
            category="Developer",
            hint="Contains all simulator devices and their installed apps and data.",
            impact="⚠️ ALL simulator devices and their app data will be deleted.",
            risk="high"
        ),
        CacheLocation(
            id="npm_cache",
            path=f"{home}/.npm/_cacache",
            name="NPM Cache",
            description="Downloaded NPM packages cache",
            category="Packages",
            hint="NPM stores downloaded packages here to avoid re-downloading them.",
            impact="NPM will re-download packages when needed.",
            risk="low"
        ),
        CacheLocation(
            id="yarn_cache",
            path=f"{home}/.yarn/cache",
            name="Yarn Cache",
            description="Downloaded Yarn packages cache",
            category="Packages",
            hint="Yarn's offline cache of all packages.",
            impact="Yarn will need to re-download packages.",
            risk="low"
        ),
        CacheLocation(
            id="pip_cache",
            path=f"{home}/.cache/pip",
            name="Python Pip Cache",
            description="Downloaded Python packages cache",
            category="Packages",
            hint="Pip caches downloaded wheel and source packages here.",
            impact="Pip will re-download packages when installing.",
            risk="low"
        ),
        CacheLocation(
            id="pub_cache",
            path=f"{home}/.pub-cache",
            name="Flutter/Dart Pub Cache",
            description="Dart and Flutter packages",
            category="Packages",
            hint="Contains all Flutter and Dart packages.",
            impact="Run 'flutter pub get' again after cleaning.",
            risk="low"
        ),
        CacheLocation(
            id="gradle_cache",
            path=f"{home}/.gradle/caches",
            name="Gradle Cache",
            description="Android/Java build cache",
            category="Packages",
            hint="Gradle stores downloaded dependencies and build outputs here.",
            impact="Android/Gradle builds will re-download dependencies.",
            risk="low"
        ),
        CacheLocation(
            id="cocoapods",
            path=f"{home}/.cocoapods/repos",
            name="CocoaPods Repos",
            description="CocoaPods spec repositories",
            category="Packages",
            hint="Contains the CocoaPods master spec repo. Can be 1-2GB.",
            impact="Next 'pod install' will re-clone spec repos.",
            risk="low"
        ),
        CacheLocation(
            id="safari_cache",
            path=f"{home}/Library/Caches/com.apple.Safari",
            name="Safari Cache",
            description="Safari browser cache",
            category="Browsers",
            hint="Contains cached web pages, images, scripts from Safari.",
            impact="Websites will reload fresh content. Login sessions preserved.",
            risk="low"
        ),
        CacheLocation(
            id="chrome_cache",
            path=f"{home}/Library/Caches/Google/Chrome/Default/Cache",
            name="Chrome Cache",
            description="Chrome browser cache",
            category="Browsers",
            hint="Chrome's cached web content.",
            impact="Chrome will re-download web content. Cookies and history preserved.",
            risk="low"
        ),
        CacheLocation(
            id="firefox_cache",
            path=f"{home}/Library/Caches/Firefox",
            name="Firefox Cache",
            description="Firefox browser cache",
            category="Browsers",
            hint="Firefox's cached web content.",
            impact="Firefox will reload content. Login sessions safe.",
            risk="low"
        ),
        CacheLocation(
            id="vscode_cache",
            path=f"{home}/Library/Application Support/Code/CachedData",
            name="VS Code Cache",
            description="Visual Studio Code cached data",
            category="Applications",
            hint="VS Code caches extension data and workspace state.",
            impact="VS Code may take slightly longer to start.",
            risk="low"
        ),
        CacheLocation(
            id="slack_cache",
            path=f"{home}/Library/Application Support/Slack/Cache",
            name="Slack Cache",
            description="Slack cached messages and files",
            category="Applications",
            hint="Contains cached messages, files, and images from Slack.",
            impact="Slack will re-download message history and files.",
            risk="low"
        ),
        CacheLocation(
            id="discord_cache",
            path=f"{home}/Library/Application Support/discord/Cache",
            name="Discord Cache",
            description="Discord cached content",
            category="Applications",
            hint="Cached images, videos, and other media from Discord.",
            impact="Discord will re-download media from channels.",
            risk="low"
        ),
        CacheLocation(
            id="spotify_cache",
            path=f"{home}/Library/Application Support/Spotify/PersistentCache",
            name="Spotify Cache",
            description="Spotify offline music cache",
            category="Applications",
            hint="Contains cached and downloaded music for offline playback.",
            impact="⚠️ Downloaded songs for offline will be removed.",
            risk="medium"
        ),
        CacheLocation(
            id="docker_data",
            path=f"{home}/Library/Containers/com.docker.docker/Data/vms",
            name="Docker VM Data",
            description="Docker Desktop VM disk images",
            category="Docker",
            hint="Docker Desktop runs in a VM. This contains all containers and images.",
            impact="⚠️ ALL Docker images, containers, and volumes will be deleted.",
            risk="high"
        ),
        CacheLocation(
            id="tmp",
            path="/tmp",
            name="System Temp Files",
            description="Temporary files from running apps",
            category="Temp",
            hint="Standard Unix temp directory. Cleared on reboot.",
            impact="Running apps may lose temporary work. Close apps first.",
            risk="low"
        ),
        CacheLocation(
            id="user_logs",
            path=f"{home}/Library/Logs",
            name="User Application Logs",
            description="Log files from applications",
            category="Logs",
            hint="Applications store their log files here for debugging.",
            impact="Historical logs will be lost. Apps create new logs as needed.",
            risk="low"
        ),
        CacheLocation(
            id="ios_backups",
            path=f"{home}/Library/Application Support/MobileSync/Backup",
            name="iOS Device Backups",
            description="iPhone/iPad local backups",
            category="Backups",
            hint="Local backups of iOS devices. Each can be 10-100GB.",
            impact="⚠️ ALL local device backups will be permanently deleted.",
            risk="high"
        ),
        CacheLocation(
            id="homebrew_cache",
            path=f"{home}/Library/Caches/Homebrew",
            name="Homebrew Downloads",
            description="Downloaded Homebrew packages",
            category="Packages",
            hint="Homebrew caches downloaded bottles and source archives.",
            impact="Homebrew will re-download packages if reinstalled.",
            risk="low"
        ),
    ]
    
    return locations


# Routes
@app.route('/')
def index():
    return render_template('app.html')


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('assets', filename)


@app.route('/api/scan', methods=['POST'])
def start_scan():
    global scan_results, scan_in_progress, scan_complete, scan_progress
    
    if scan_in_progress:
        return jsonify({"status": "already_scanning"})
    
    scan_in_progress = True
    scan_complete = False
    scan_results = []
    scan_progress = {"current": 0, "total": 0, "percent": 0, "current_location": "", "found_count": 0, "total_size": 0}
    
    def do_scan():
        global scan_results, scan_in_progress, scan_complete, scan_progress
        locations = get_cache_locations()
        results = []
        
        total_locations = len(locations)
        scan_progress["total"] = total_locations + 1
        
        for i, loc in enumerate(locations):
            scan_progress["current"] = i + 1
            scan_progress["current_location"] = loc.name
            scan_progress["percent"] = int((i / (total_locations + 1)) * 100)
            
            path = Path(loc.path)
            if path.exists():
                loc.exists = True
                loc.size = get_directory_size(loc.path)
                loc.size_human = human_readable_size(loc.size)
                if loc.size > 0:
                    loc.selected = True
                    results.append(loc)
                    scan_progress["found_count"] = len(results)
                    scan_progress["total_size"] = sum(r.size for r in results)
        
        # Scan container caches
        scan_progress["current_location"] = "Container Apps"
        home = get_home()
        containers_path = Path(f"{home}/Library/Containers")
        if containers_path.exists():
            for container in containers_path.iterdir():
                cache_path = container / "Data" / "Library" / "Caches"
                if cache_path.exists() and cache_path.is_dir():
                    app_name = container.name.split('.')[-1] if '.' in container.name else container.name
                    size = get_directory_size(str(cache_path))
                    if size > 0:
                        results.append(CacheLocation(
                            id=f"container_{app_name}",
                            path=str(cache_path),
                            name=f"{app_name} Cache",
                            description=f"Sandboxed app cache for {app_name}",
                            category="Containers",
                            hint=f"Cache data for the sandboxed app '{app_name}'.",
                            impact="The app will recreate its cache as needed.",
                            risk="low",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True,
                            exists=True
                        ))
                        scan_progress["found_count"] = len(results)
                        scan_progress["total_size"] = sum(r.size for r in results)
        
        scan_progress["percent"] = 100
        scan_progress["current_location"] = "Complete"
        
        results.sort(key=lambda x: x.size, reverse=True)
        scan_results = results
        scan_in_progress = False
        scan_complete = True
    
    thread = threading.Thread(target=do_scan)
    thread.start()
    
    return jsonify({"status": "started"})


@app.route('/api/scan/status')
def scan_status():
    return jsonify({
        "in_progress": scan_in_progress,
        "complete": scan_complete,
        "count": len(scan_results),
        "current_location": scan_progress.get("current_location", ""),
        "progress": scan_progress
    })


@app.route('/api/locations')
def get_locations():
    return jsonify([asdict(loc) for loc in scan_results])


@app.route('/api/clean', methods=['POST'])
def clean_locations():
    data = request.json
    ids_to_clean = data.get('ids', [])
    
    results = []
    for loc in scan_results:
        if loc.id in ids_to_clean:
            success = False
            message = ""
            try:
                path = Path(loc.path)
                if path.is_dir():
                    for item in path.iterdir():
                        try:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                        except:
                            pass
                    success = True
                    message = "Cleaned"
                elif path.is_file():
                    path.unlink()
                    success = True
                    message = "Deleted"
            except PermissionError:
                message = "Permission denied"
            except Exception as e:
                message = str(e)
            
            results.append({
                "id": loc.id,
                "name": loc.name,
                "success": success,
                "message": message
            })
    
    return jsonify({"results": results})


# ============================================================================
# LEFTOVER SCANNING ENDPOINTS
# ============================================================================

@app.route('/api/scan/leftovers', methods=['POST'])
def start_leftover_scan():
    """Start scanning for uninstalled application leftovers."""
    global leftover_results, leftover_scan_in_progress, leftover_scan_complete, leftover_scan_progress
    
    if leftover_scan_in_progress:
        return jsonify({"status": "already_scanning"})
    
    leftover_scan_in_progress = True
    leftover_scan_complete = False
    leftover_results = []
    leftover_scan_progress = {
        "current": 0, "total": 7, "percent": 0,
        "current_location": "Initializing...",
        "found_count": 0, "total_size": 0
    }
    
    def do_leftover_scan():
        global leftover_results, leftover_scan_in_progress, leftover_scan_complete, leftover_scan_progress
        
        results = []
        
        # Step 1: Get installed bundle IDs
        leftover_scan_progress["current_location"] = "Scanning installed applications..."
        leftover_scan_progress["current"] = 1
        leftover_scan_progress["percent"] = 10
        
        installed_ids = get_installed_bundle_ids()
        
        # Step 2: Scan Containers
        leftover_scan_progress["current_location"] = "Scanning Containers..."
        leftover_scan_progress["current"] = 2
        leftover_scan_progress["percent"] = 25
        results.extend(detect_container_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Step 3: Scan Group Containers
        leftover_scan_progress["current_location"] = "Scanning Group Containers..."
        leftover_scan_progress["current"] = 3
        leftover_scan_progress["percent"] = 40
        results.extend(detect_group_container_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Step 4: Scan Application Support
        leftover_scan_progress["current_location"] = "Scanning Application Support..."
        leftover_scan_progress["current"] = 4
        leftover_scan_progress["percent"] = 55
        results.extend(detect_app_support_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Step 5: Scan Preferences
        leftover_scan_progress["current_location"] = "Scanning Preferences..."
        leftover_scan_progress["current"] = 5
        leftover_scan_progress["percent"] = 70
        results.extend(detect_preference_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Step 6: Scan Launch Agents
        leftover_scan_progress["current_location"] = "Scanning Launch Agents..."
        leftover_scan_progress["current"] = 6
        leftover_scan_progress["percent"] = 85
        results.extend(detect_launch_agent_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Step 7: Scan Caches (orphan caches only)
        leftover_scan_progress["current_location"] = "Scanning Orphan Caches..."
        leftover_scan_progress["current"] = 7
        leftover_scan_progress["percent"] = 95
        results.extend(detect_cache_orphans(installed_ids))
        leftover_scan_progress["found_count"] = len(results)
        leftover_scan_progress["total_size"] = sum(r.size for r in results)
        
        # Done
        leftover_scan_progress["percent"] = 100
        leftover_scan_progress["current_location"] = "Complete"
        
        # Sort by size (largest first)
        results.sort(key=lambda x: x.size, reverse=True)
        
        leftover_results = results
        leftover_scan_in_progress = False
        leftover_scan_complete = True
    
    thread = threading.Thread(target=do_leftover_scan)
    thread.start()
    
    return jsonify({"status": "started"})


@app.route('/api/scan/leftovers/status')
def leftover_scan_status():
    """Get the status of the leftover scan."""
    return jsonify({
        "in_progress": leftover_scan_in_progress,
        "complete": leftover_scan_complete,
        "count": len(leftover_results),
        "current_location": leftover_scan_progress.get("current_location", ""),
        "progress": leftover_scan_progress
    })


@app.route('/api/leftovers')
def get_leftovers():
    """Return detected leftover items."""
    return jsonify([asdict(item) for item in leftover_results])


@app.route('/api/clean/leftovers', methods=['POST'])
def clean_leftovers():
    """Clean selected leftover items."""
    data = request.json
    ids_to_clean = data.get('ids', [])
    
    results = []
    for item in leftover_results:
        if item.id in ids_to_clean:
            success = False
            message = ""
            try:
                path = Path(item.path)
                if path.is_dir():
                    shutil.rmtree(path)
                    success = True
                    message = "Deleted folder"
                elif path.is_file():
                    path.unlink()
                    success = True
                    message = "Deleted file"
            except PermissionError:
                message = "Permission denied"
            except Exception as e:
                message = str(e)
            
            results.append({
                "id": item.id,
                "name": item.name,
                "success": success,
                "message": message
            })
    
    return jsonify({"results": results})


@app.route('/api/installed-apps')
def get_installed_apps_list():
    """Return list of currently installed application bundle IDs (for debugging)."""
    bundle_ids = get_installed_bundle_ids()
    return jsonify({
        "count": len(bundle_ids),
        "bundle_ids": sorted(list(bundle_ids))
    })


# System monitoring endpoints
@app.route('/api/system/stats')
def system_stats():
    stats = {
        "cpu_percent": 0,
        "cpu_count": 0,
        "memory": {"total": 0, "used": 0, "free": 0, "percent": 0, "total_human": "N/A", "used_human": "N/A", "free_human": "N/A"},
        "disk": {"total": 0, "used": 0, "free": 0, "percent": 0, "total_human": "N/A", "used_human": "N/A", "free_human": "N/A"},
        "network": {"bytes_sent": 0, "bytes_recv": 0, "sent_human": "0 B", "recv_human": "0 B"},
        "uptime": "N/A"
    }
    
    if PSUTIL_AVAILABLE:
        stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        stats["cpu_count"] = psutil.cpu_count()
        
        mem = psutil.virtual_memory()
        stats["memory"] = {
            "total": mem.total,
            "used": mem.used,
            "free": mem.available,
            "percent": mem.percent,
            "total_human": human_readable_size(mem.total),
            "used_human": human_readable_size(mem.used),
            "free_human": human_readable_size(mem.available)
        }
        
        disk = psutil.disk_usage('/')
        stats["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
            "total_human": human_readable_size(disk.total),
            "used_human": human_readable_size(disk.used),
            "free_human": human_readable_size(disk.free)
        }
        
        net = psutil.net_io_counters()
        stats["network"] = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "sent_human": human_readable_size(net.bytes_sent),
            "recv_human": human_readable_size(net.bytes_recv)
        }
        
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            days, remainder = divmod(int(uptime_seconds), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            if days > 0:
                stats["uptime"] = f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                stats["uptime"] = f"{hours}h {minutes}m"
            else:
                stats["uptime"] = f"{minutes}m"
        except:
            pass
    else:
        # Fallback for disk
        try:
            result = subprocess.run(['df', '-k', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                total = int(parts[1]) * 1024
                used = int(parts[2]) * 1024
                free = int(parts[3]) * 1024
                percent = int(parts[4].replace('%', ''))
                stats["disk"] = {
                    "total": total, "used": used, "free": free, "percent": percent,
                    "total_human": human_readable_size(total),
                    "used_human": human_readable_size(used),
                    "free_human": human_readable_size(free)
                }
        except:
            pass
    
    return jsonify(stats)


@app.route('/api/system/processes')
def get_top_processes():
    processes = {"by_cpu": [], "by_memory": []}
    
    if PSUTIL_AVAILABLE:
        try:
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
                try:
                    pinfo = proc.info
                    if pinfo['cpu_percent'] is not None:
                        procs.append({
                            "pid": pinfo['pid'],
                            "name": pinfo['name'],
                            "cpu_percent": round(pinfo['cpu_percent'], 1),
                            "memory_percent": round(pinfo['memory_percent'], 1) if pinfo['memory_percent'] else 0,
                            "memory": pinfo['memory_info'].rss if pinfo['memory_info'] else 0,
                            "memory_human": human_readable_size(pinfo['memory_info'].rss if pinfo['memory_info'] else 0)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            processes["by_cpu"] = sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)[:15]
            processes["by_memory"] = sorted(procs, key=lambda x: x['memory'], reverse=True)[:15]
        except:
            pass
    
    return jsonify(processes)


def open_browser(port):
    time.sleep(1)
    webbrowser.open(f'http://127.0.0.1:{port}')


if __name__ == '__main__':
    # Find available port
    port = 5050
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                break
            port += 1

    print("\n" + "=" * 50)
    print("  Q-Cleaner Web Panel")
    print(f"  Open http://127.0.0.1:{port} in your browser")
    print("=" * 50 + "\n")
    
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='127.0.0.1', port=port, debug=False)
