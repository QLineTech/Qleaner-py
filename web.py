#!/usr/bin/env python3
"""
Q-Cleaner Web Panel for macOS
A web-based cache and temp file cleaner with detailed explanations
Enhanced with system monitoring and statistics
"""

import os
import shutil
import subprocess
import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any
from flask import Flask, render_template, jsonify, request
import webbrowser

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. System monitoring features will be limited.")
    print("Install with: pip install psutil")

app = Flask(__name__)

# Store scan results globally for the session
scan_results = []
scan_in_progress = False
scan_complete = False

# Progress tracking for detailed updates
scan_progress = {
    "current": 0,
    "total": 0,
    "percent": 0,
    "current_location": "",
    "found_count": 0,
    "total_size": 0
}

# System monitoring history
system_history = {
    "cpu": [],
    "memory": [],
    "network_in": [],
    "network_out": [],
    "timestamps": []
}
history_lock = threading.Lock()
MAX_HISTORY_POINTS = 60  # Keep last 60 data points


@dataclass
class CacheLocation:
    id: str
    path: str
    name: str
    description: str
    category: str
    hint: str  # Detailed explanation
    impact: str  # What happens when cleaned
    risk: str  # low, medium, high
    size: int = 0
    size_human: str = "0B"
    selected: bool = False
    exists: bool = False


def get_home() -> str:
    return str(Path.home())


def human_readable_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return "0B"
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


def get_cache_locations() -> List[CacheLocation]:
    home = get_home()
    
    locations = [
        # System Caches
        CacheLocation(
            id="user_caches",
            path=f"{home}/Library/Caches",
            name="User Application Caches",
            description="Cache files from all your applications",
            category="System",
            hint="This folder contains cached data from all applications you use. Apps store temporary files here to speed up loading times and reduce network requests. Each app has its own subfolder.",
            impact="Apps will need to re-download or regenerate their cached data. This may cause slower initial load times but is generally safe. Login sessions are usually preserved.",
            risk="low"
        ),
        CacheLocation(
            id="system_caches",
            path="/Library/Caches",
            name="System Application Caches",
            description="System-wide application caches",
            category="System",
            hint="Contains cached data for system-level applications and services. These are shared across all users on the Mac.",
            impact="System apps will regenerate caches as needed. May require admin password. Generally safe but may cause temporary slowdowns.",
            risk="medium"
        ),
        
        # Xcode
        CacheLocation(
            id="xcode_derived",
            path=f"{home}/Library/Developer/Xcode/DerivedData",
            name="Xcode DerivedData",
            description="Xcode build intermediates and indexes",
            category="Developer",
            hint="Contains all build products, indexes, and logs from Xcode projects. Each project gets its own folder with compiled code, symbol indexes, and build logs.",
            impact="Next build will take longer as Xcode rebuilds everything from scratch. All build caches, indexes, and logs will be regenerated. Your source code is NOT affected.",
            risk="low"
        ),
        CacheLocation(
            id="xcode_archives",
            path=f"{home}/Library/Developer/Xcode/Archives",
            name="Xcode Archives",
            description="App Store submission archives",
            category="Developer",
            hint="Contains archived builds used for App Store submissions and ad-hoc distribution. Each archive includes the complete app bundle, dSYM files for crash reports, and metadata.",
            impact="⚠️ You will lose the ability to symbolicate crash reports from these builds. Delete only if you no longer need to debug crashes from released versions.",
            risk="high"
        ),
        CacheLocation(
            id="xcode_device_support",
            path=f"{home}/Library/Developer/Xcode/iOS DeviceSupport",
            name="iOS Device Support",
            description="Debug symbols for iOS devices",
            category="Developer",
            hint="Contains debug symbols for each iOS version you've connected via USB. Required for debugging on physical devices. Each iOS version you've used has its own folder (often 2-5GB each!).",
            impact="Xcode will re-download symbols when you next connect a device with that iOS version. May take several minutes. Device debugging will work after re-download.",
            risk="low"
        ),
        CacheLocation(
            id="simulator_caches",
            path=f"{home}/Library/Developer/CoreSimulator/Caches",
            name="iOS Simulator Caches",
            description="Cached data for iOS Simulator",
            category="Developer",
            hint="Contains cached runtime data, screenshots, and temporary files from iOS Simulator sessions.",
            impact="Simulators will recreate caches as needed. No data loss. Safe to delete.",
            risk="low"
        ),
        CacheLocation(
            id="simulator_devices",
            path=f"{home}/Library/Developer/CoreSimulator/Devices",
            name="iOS Simulator Devices",
            description="All iOS Simulator instances and their data",
            category="Developer",
            hint="Contains all your simulator devices and their installed apps, data, and settings. Each simulator (iPhone 14, iPad Pro, etc.) has its own folder.",
            impact="⚠️ ALL simulator devices and their app data will be deleted. You'll need to recreate simulators in Xcode. Apps installed on simulators will be lost.",
            risk="high"
        ),
        
        # Package Managers
        CacheLocation(
            id="npm_cache",
            path=f"{home}/.npm/_cacache",
            name="NPM Cache",
            description="Downloaded NPM packages cache",
            category="Packages",
            hint="NPM stores downloaded packages here to avoid re-downloading them. Contains compressed tarballs and integrity metadata for all packages you've ever installed.",
            impact="NPM will re-download packages when needed. Internet connection required. First 'npm install' after cleaning will be slower.",
            risk="low"
        ),
        CacheLocation(
            id="yarn_cache",
            path=f"{home}/.yarn/cache",
            name="Yarn Cache",
            description="Downloaded Yarn packages cache",
            category="Packages",
            hint="Yarn's offline cache of all packages. Allows Yarn to work offline and speeds up installations significantly.",
            impact="Yarn will need to re-download packages. If using Yarn PnP, you may also need to run 'yarn install' in projects.",
            risk="low"
        ),
        CacheLocation(
            id="pnpm_store",
            path=f"{home}/.pnpm-store",
            name="PNPM Store",
            description="PNPM's content-addressable storage",
            category="Packages",
            hint="PNPM uses a global content-addressable store to save disk space. All packages are stored once and hard-linked to projects.",
            impact="PNPM will re-download packages when running 'pnpm install'. May temporarily increase disk usage in projects until rebuilt.",
            risk="low"
        ),
        CacheLocation(
            id="pip_cache",
            path=f"{home}/.cache/pip",
            name="Python Pip Cache",
            description="Downloaded Python packages cache",
            category="Packages",
            hint="Pip caches downloaded wheel and source packages here. Speeds up reinstallation of packages.",
            impact="Pip will re-download packages when installing. Virtual environments are not affected.",
            risk="low"
        ),
        CacheLocation(
            id="pub_cache",
            path=f"{home}/.pub-cache",
            name="Flutter/Dart Pub Cache",
            description="Dart and Flutter packages cache",
            category="Packages",
            hint="Contains all Flutter and Dart packages downloaded via 'pub get' or 'flutter pub get'. Also includes activated global tools.",
            impact="Flutter/Dart projects will need to run 'flutter pub get' again. Global tools will need reinstallation.",
            risk="low"
        ),
        CacheLocation(
            id="cocoapods",
            path=f"{home}/.cocoapods/repos",
            name="CocoaPods Repos",
            description="CocoaPods spec repositories",
            category="Packages",
            hint="Contains the CocoaPods master spec repo and any private spec repos. The master repo alone can be 1-2GB.",
            impact="Next 'pod install' will re-clone the spec repos. This can take several minutes on first run.",
            risk="low"
        ),
        CacheLocation(
            id="gradle_cache",
            path=f"{home}/.gradle/caches",
            name="Gradle Cache",
            description="Android/Java build cache",
            category="Packages",
            hint="Gradle stores downloaded dependencies, build outputs, and wrappers here. Essential for Android development.",
            impact="Android/Gradle builds will re-download dependencies. First build will be significantly slower.",
            risk="low"
        ),
        CacheLocation(
            id="maven_cache",
            path=f"{home}/.m2/repository",
            name="Maven Repository",
            description="Maven local repository cache",
            category="Packages",
            hint="Maven stores all downloaded JAR files and POMs here. Shared across all Maven and some Gradle projects.",
            impact="Maven will re-download dependencies on next build. Can be slow for large projects.",
            risk="low"
        ),
        CacheLocation(
            id="cargo_cache",
            path=f"{home}/.cargo/registry",
            name="Rust Cargo Registry",
            description="Rust crates cache",
            category="Packages",
            hint="Contains downloaded Rust crates (packages) and their sources. Used by all Rust projects on your system.",
            impact="Cargo will re-download crates when building. First 'cargo build' will be slower.",
            risk="low"
        ),
        
        # Browsers
        CacheLocation(
            id="safari_cache",
            path=f"{home}/Library/Caches/com.apple.Safari",
            name="Safari Cache",
            description="Safari browser cache",
            category="Browsers",
            hint="Contains cached web pages, images, scripts, and other resources from websites you've visited in Safari.",
            impact="Websites will reload fresh content. May feel slower initially. Cookies and login sessions are NOT affected.",
            risk="low"
        ),
        CacheLocation(
            id="chrome_cache",
            path=f"{home}/Library/Caches/Google/Chrome/Default/Cache",
            name="Chrome Cache",
            description="Chrome browser cache",
            category="Browsers",
            hint="Chrome's cached web content including images, scripts, and media from visited websites.",
            impact="Chrome will re-download web content. Cookies, history, and bookmarks are preserved in a different location.",
            risk="low"
        ),
        CacheLocation(
            id="firefox_cache",
            path=f"{home}/Library/Caches/Firefox",
            name="Firefox Cache",
            description="Firefox browser cache",
            category="Browsers",
            hint="Firefox's cached web content from browsing sessions.",
            impact="Firefox will reload content from websites. Login sessions and bookmarks are safe.",
            risk="low"
        ),
        CacheLocation(
            id="edge_cache",
            path=f"{home}/Library/Caches/com.microsoft.Edge",
            name="Edge Cache",
            description="Microsoft Edge browser cache",
            category="Browsers",
            hint="Edge browser's cached web resources.",
            impact="Edge will refresh content. Passwords and bookmarks are not affected.",
            risk="low"
        ),
        CacheLocation(
            id="brave_cache",
            path=f"{home}/Library/Caches/com.brave.Browser",
            name="Brave Cache",
            description="Brave browser cache",
            category="Browsers",
            hint="Brave browser's cached web content.",
            impact="Cached websites will reload fresh. Privacy features and settings unaffected.",
            risk="low"
        ),
        
        # Applications
        CacheLocation(
            id="vscode_cache",
            path=f"{home}/Library/Application Support/Code/CachedData",
            name="VS Code Cache",
            description="Visual Studio Code cached data",
            category="Applications",
            hint="VS Code caches extension data, workspace state, and performance data here.",
            impact="VS Code may take slightly longer to start. Extensions and settings are preserved.",
            risk="low"
        ),
        CacheLocation(
            id="slack_cache",
            path=f"{home}/Library/Application Support/Slack/Cache",
            name="Slack Cache",
            description="Slack cached messages and files",
            category="Applications",
            hint="Contains cached messages, files, and images from Slack workspaces.",
            impact="Slack will re-download message history and files. May feel slower scrolling through old messages initially.",
            risk="low"
        ),
        CacheLocation(
            id="discord_cache",
            path=f"{home}/Library/Application Support/discord/Cache",
            name="Discord Cache",
            description="Discord cached content",
            category="Applications",
            hint="Cached images, videos, and other media from Discord channels.",
            impact="Discord will re-download media from channels. Chat history remains on Discord servers.",
            risk="low"
        ),
        CacheLocation(
            id="spotify_cache",
            path=f"{home}/Library/Application Support/Spotify/PersistentCache",
            name="Spotify Cache",
            description="Spotify offline music cache",
            category="Applications",
            hint="Contains cached and downloaded music for offline playback. Can grow very large with 'Download' playlists.",
            impact="⚠️ Downloaded songs for offline will be removed. You'll need to re-download them. Streaming works immediately.",
            risk="medium"
        ),
        
        # Docker
        CacheLocation(
            id="docker_data",
            path=f"{home}/Library/Containers/com.docker.docker/Data/vms",
            name="Docker VM Data",
            description="Docker Desktop VM disk images",
            category="Docker",
            hint="Docker Desktop runs in a VM. This contains the VM's disk images including all containers, images, and volumes.",
            impact="⚠️ ALL Docker images, containers, and volumes will be deleted. You'll need to pull images and recreate containers.",
            risk="high"
        ),
        CacheLocation(
            id="docker_buildx",
            path=f"{home}/.docker/buildx",
            name="Docker Buildx Cache",
            description="Docker build cache",
            category="Docker",
            hint="Cache for Docker's BuildKit builder. Speeds up subsequent image builds.",
            impact="Docker builds will start fresh without layer caching. First builds will be slower.",
            risk="low"
        ),
        
        # System
        CacheLocation(
            id="tmp",
            path="/tmp",
            name="System Temp Files",
            description="Temporary files created by running apps",
            category="Temp",
            hint="Standard Unix temp directory. Apps store temporary files here that should be safe to delete. System clears this on reboot.",
            impact="Running apps may lose temporary work. Best to close apps first. Cleared on every restart anyway.",
            risk="low"
        ),
        CacheLocation(
            id="var_folders",
            path="/var/folders",
            name="System Cache Folders",
            description="Per-user temporary items and caches",
            category="Temp",
            hint="macOS creates per-user cache directories here for temporary files, caches, and inter-process communication.",
            impact="Apps may need to recreate temporary files. Usually safe but close important apps first.",
            risk="medium"
        ),
        CacheLocation(
            id="user_logs",
            path=f"{home}/Library/Logs",
            name="User Application Logs",
            description="Log files from applications",
            category="Logs",
            hint="Applications store their log files here for debugging. Useful for troubleshooting but can grow large over time.",
            impact="Historical logs will be lost. Useful for troubleshooting. Apps will create new logs as needed.",
            risk="low"
        ),
        CacheLocation(
            id="system_logs",
            path="/var/log",
            name="System Logs",
            description="macOS system log files",
            category="Logs",
            hint="System-wide logs including security, install, and system events. Managed by macOS log rotation.",
            impact="Historical system logs removed. New logs created automatically. May need sudo.",
            risk="medium"
        ),
        
        # Large Items
        CacheLocation(
            id="ios_backups",
            path=f"{home}/Library/Application Support/MobileSync/Backup",
            name="iOS Device Backups",
            description="iPhone/iPad local backups",
            category="Backups",
            hint="Local backups of iOS devices made through Finder/iTunes. Each backup can be 10-100GB depending on device data.",
            impact="⚠️ ALL local device backups will be permanently deleted. You won't be able to restore devices from these backups. iCloud backups (if enabled) are not affected.",
            risk="high"
        ),
        CacheLocation(
            id="mail_cache",
            path=f"{home}/Library/Caches/com.apple.mail",
            name="Mail Cache",
            description="Apple Mail cached data",
            category="System",
            hint="Mail.app caches email content, attachments previews, and search indexes here.",
            impact="Mail will re-download and re-index emails. May take a while for large mailboxes. Emails on server are safe.",
            risk="low"
        ),
        CacheLocation(
            id="homebrew_cache",
            path=f"{home}/Library/Caches/Homebrew",
            name="Homebrew Downloads",
            description="Downloaded Homebrew packages",
            category="Packages",
            hint="Homebrew caches downloaded bottles (precompiled packages) and source archives here.",
            impact="Homebrew will re-download packages if you reinstall them. Installed packages continue to work.",
            risk="low"
        ),
    ]
    
    return locations


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/scan', methods=['POST'])
def start_scan():
    global scan_results, scan_in_progress, scan_complete, scan_progress
    
    if scan_in_progress:
        return jsonify({"status": "already_scanning"})
    
    scan_in_progress = True
    scan_complete = False
    scan_results = []
    scan_progress = {
        "current": 0,
        "total": 0,
        "percent": 0,
        "current_location": "",
        "found_count": 0,
        "total_size": 0
    }
    
    def do_scan():
        global scan_results, scan_in_progress, scan_complete, scan_progress
        locations = get_cache_locations()
        results = []
        
        total_locations = len(locations)
        scan_progress["total"] = total_locations + 1  # +1 for containers scan
        
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
                    scan_progress["current_location"] = f"Container: {app_name}"
                    size = get_directory_size(str(cache_path))
                    if size > 0:
                        results.append(CacheLocation(
                            id=f"container_{app_name}",
                            path=str(cache_path),
                            name=f"{app_name} Cache",
                            description=f"Sandboxed app cache for {app_name}",
                            category="Containers",
                            hint=f"Cache data for the sandboxed macOS app '{app_name}'. Sandboxed apps store their data in isolated containers.",
                            impact="The app will recreate its cache as needed. App data and settings in the container are preserved.",
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
        
        # Sort by size descending
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
        "progress": {
            "current": scan_progress.get("current", 0),
            "total": scan_progress.get("total", 0),
            "percent": scan_progress.get("percent", 0),
            "found_count": scan_progress.get("found_count", 0),
            "total_size": scan_progress.get("total_size", 0)
        }
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


# ============================================
# System Monitoring API Endpoints
# ============================================

def get_disk_usage():
    """Get disk usage for the main disk."""
    try:
        if PSUTIL_AVAILABLE:
            disk = psutil.disk_usage('/')
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent,
                "total_human": human_readable_size(disk.total),
                "used_human": human_readable_size(disk.used),
                "free_human": human_readable_size(disk.free)
            }
        else:
            # Fallback using df command
            result = subprocess.run(['df', '-k', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                total = int(parts[1]) * 1024
                used = int(parts[2]) * 1024
                free = int(parts[3]) * 1024
                percent = int(parts[4].replace('%', ''))
                return {
                    "total": total,
                    "used": used,
                    "free": free,
                    "percent": percent,
                    "total_human": human_readable_size(total),
                    "used_human": human_readable_size(used),
                    "free_human": human_readable_size(free)
                }
    except Exception as e:
        pass
    return {"total": 0, "used": 0, "free": 0, "percent": 0, "total_human": "N/A", "used_human": "N/A", "free_human": "N/A"}


@app.route('/api/system/stats')
def system_stats():
    """Get real-time system statistics."""
    stats = {
        "cpu_percent": 0,
        "memory": {"total": 0, "used": 0, "free": 0, "percent": 0},
        "disk": get_disk_usage(),
        "network": {"bytes_sent": 0, "bytes_recv": 0, "sent_human": "0 B", "recv_human": "0 B"},
        "uptime": "N/A"
    }
    
    if PSUTIL_AVAILABLE:
        # CPU
        stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        stats["cpu_count"] = psutil.cpu_count()
        
        # Memory
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
        
        # Network
        net = psutil.net_io_counters()
        stats["network"] = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "sent_human": human_readable_size(net.bytes_sent),
            "recv_human": human_readable_size(net.bytes_recv)
        }
        
        # Uptime
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
    
    # Update history
    with history_lock:
        system_history["cpu"].append(stats["cpu_percent"])
        system_history["memory"].append(stats["memory"]["percent"])
        system_history["network_in"].append(stats["network"]["bytes_recv"])
        system_history["network_out"].append(stats["network"]["bytes_sent"])
        system_history["timestamps"].append(time.time())
        
        # Trim to max size
        for key in ["cpu", "memory", "network_in", "network_out", "timestamps"]:
            if len(system_history[key]) > MAX_HISTORY_POINTS:
                system_history[key] = system_history[key][-MAX_HISTORY_POINTS:]
    
    return jsonify(stats)


@app.route('/api/system/history')
def get_system_history():
    """Get historical system data for charts."""
    with history_lock:
        # Calculate network rate (bytes/sec)
        network_rate_in = []
        network_rate_out = []
        for i in range(1, len(system_history["timestamps"])):
            time_diff = system_history["timestamps"][i] - system_history["timestamps"][i-1]
            if time_diff > 0:
                rate_in = (system_history["network_in"][i] - system_history["network_in"][i-1]) / time_diff
                rate_out = (system_history["network_out"][i] - system_history["network_out"][i-1]) / time_diff
                network_rate_in.append(max(0, rate_in))
                network_rate_out.append(max(0, rate_out))
        
        return jsonify({
            "cpu": system_history["cpu"],
            "memory": system_history["memory"],
            "network_in": network_rate_in,
            "network_out": network_rate_out,
            "labels": list(range(len(system_history["cpu"])))
        })


@app.route('/api/system/processes')
def get_top_processes():
    """Get top processes by CPU and memory usage."""
    processes = {
        "by_cpu": [],
        "by_memory": []
    }
    
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
            
            # Sort by CPU and get top 10
            by_cpu = sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)[:10]
            # Sort by memory and get top 10
            by_memory = sorted(procs, key=lambda x: x['memory_percent'], reverse=True)[:10]
            
            processes["by_cpu"] = by_cpu
            processes["by_memory"] = by_memory
            
        except Exception as e:
            pass
    
    return jsonify(processes)


@app.route('/api/system/disk/volumes')
def get_disk_volumes():
    """Get all disk volumes/mounts."""
    volumes = []
    
    if PSUTIL_AVAILABLE:
        try:
            partitions = psutil.disk_partitions(all=False)
            for part in partitions:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    volumes.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                        "total_human": human_readable_size(usage.total),
                        "used_human": human_readable_size(usage.used),
                        "free_human": human_readable_size(usage.free)
                    })
                except:
                    pass
        except Exception as e:
            pass
    else:
        # Fallback: just main disk
        disk = get_disk_usage()
        if disk["total"] > 0:
            volumes.append({
                "device": "Macintosh HD",
                "mountpoint": "/",
                "fstype": "APFS",
                **disk
            })
    
    return jsonify(volumes)


# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Q-Cleaner - macOS Cache Cleaner</title>
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --bg-hover: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --border-color: #30363d;
            --accent: #58a6ff;
            --accent-hover: #79b8ff;
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
            --gradient-1: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --gradient-2: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --shadow: 0 8px 24px rgba(0,0,0,0.4);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header */
        .header {
            text-align: center;
            padding: 40px 20px;
            background: var(--gradient-1);
            border-radius: 16px;
            margin-bottom: 24px;
            box-shadow: var(--shadow);
        }
        
        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 8px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        
        .header p {
            opacity: 0.9;
            font-size: 1.1rem;
        }
        
        /* Controls */
        .controls {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn-primary {
            background: var(--accent);
            color: white;
        }
        
        .btn-primary:hover {
            background: var(--accent-hover);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(88, 166, 255, 0.4);
        }
        
        .btn-danger {
            background: var(--danger);
            color: white;
        }
        
        .btn-danger:hover {
            filter: brightness(1.1);
            transform: translateY(-2px);
        }
        
        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }
        
        .btn-secondary:hover {
            background: var(--bg-hover);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none !important;
        }
        
        /* Summary */
        .summary {
            display: flex;
            gap: 20px;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }
        
        .summary-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            flex: 1;
            min-width: 200px;
        }
        
        .summary-card h3 {
            font-size: 0.85rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        
        .summary-card .value {
            font-size: 2rem;
            font-weight: 700;
        }
        
        .summary-card .value.size { color: var(--danger); }
        .summary-card .value.count { color: var(--accent); }
        
        /* Categories */
        .category-filters {
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .category-btn {
            padding: 8px 16px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        
        .category-btn:hover, .category-btn.active {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        /* Location Cards */
        .locations-grid {
            display: grid;
            gap: 16px;
        }
        
        .location-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            transition: all 0.2s ease;
            position: relative;
        }
        
        .location-card:hover {
            border-color: var(--accent);
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        
        .location-card.selected {
            border-color: var(--success);
            background: rgba(63, 185, 80, 0.05);
        }
        
        .location-header {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            margin-bottom: 12px;
        }
        
        .checkbox-wrapper {
            position: relative;
            width: 24px;
            height: 24px;
            flex-shrink: 0;
        }
        
        .checkbox-wrapper input {
            width: 24px;
            height: 24px;
            cursor: pointer;
            opacity: 0;
            position: absolute;
        }
        
        .checkbox-custom {
            width: 24px;
            height: 24px;
            border: 2px solid var(--border-color);
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            background: var(--bg-tertiary);
        }
        
        .checkbox-wrapper input:checked + .checkbox-custom {
            background: var(--success);
            border-color: var(--success);
        }
        
        .checkbox-custom::after {
            content: '✓';
            color: white;
            font-size: 14px;
            opacity: 0;
            transition: opacity 0.2s;
        }
        
        .checkbox-wrapper input:checked + .checkbox-custom::after {
            opacity: 1;
        }
        
        .location-info {
            flex: 1;
        }
        
        .location-name {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .risk-badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .risk-low { background: rgba(63, 185, 80, 0.2); color: var(--success); }
        .risk-medium { background: rgba(210, 153, 34, 0.2); color: var(--warning); }
        .risk-high { background: rgba(248, 81, 73, 0.2); color: var(--danger); }
        
        .location-desc {
            color: var(--text-secondary);
            font-size: 0.9rem;
        }
        
        .location-path {
            color: var(--text-muted);
            font-size: 0.8rem;
            font-family: monospace;
            margin-top: 4px;
            word-break: break-all;
        }
        
        .location-size {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--danger);
            text-align: right;
            white-space: nowrap;
        }
        
        .location-size.small { color: var(--text-muted); font-size: 1.2rem; }
        .location-size.medium { color: var(--success); }
        .location-size.large { color: var(--warning); }
        .location-size.huge { color: var(--danger); }
        
        /* Hint Button & Tooltip */
        .hint-btn {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            transition: all 0.2s;
            flex-shrink: 0;
        }
        
        .hint-btn:hover {
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }
        
        .hint-panel {
            display: none;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            margin-top: 12px;
            animation: slideDown 0.2s ease;
        }
        
        @keyframes slideDown {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .hint-panel.show {
            display: block;
        }
        
        .hint-section {
            margin-bottom: 12px;
        }
        
        .hint-section:last-child {
            margin-bottom: 0;
        }
        
        .hint-section h4 {
            font-size: 0.75rem;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        
        .hint-section p {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        
        /* Progress */
        .progress-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        
        .progress-overlay.show {
            display: flex;
        }
        
        .progress-card {
            background: var(--bg-secondary);
            border-radius: 16px;
            padding: 40px;
            text-align: center;
            min-width: 300px;
        }
        
        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid var(--bg-tertiary);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-secondary);
        }
        
        .empty-state svg {
            width: 80px;
            height: 80px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
        
        /* Toast */
        .toast {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px 24px;
            display: none;
            align-items: center;
            gap: 12px;
            box-shadow: var(--shadow);
            z-index: 1001;
            animation: slideIn 0.3s ease;
        }
        
        .toast.show {
            display: flex;
        }
        
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        .toast.success { border-left: 4px solid var(--success); }
        .toast.error { border-left: 4px solid var(--danger); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧹 Q-Cleaner</h1>
            <p>macOS Cache & Temp File Cleaner</p>
        </div>
        
        <div class="controls">
            <button class="btn btn-primary" id="scanBtn" onclick="startScan()">
                <span>🔍</span> Scan System
            </button>
            <button class="btn btn-secondary" onclick="selectAll()">Select All</button>
            <button class="btn btn-secondary" onclick="selectNone()">Select None</button>
            <button class="btn btn-danger" id="cleanBtn" onclick="cleanSelected()" disabled>
                <span>🗑️</span> Clean Selected
            </button>
        </div>
        
        <div class="summary">
            <div class="summary-card">
                <h3>Selected Items</h3>
                <div class="value count" id="selectedCount">0</div>
            </div>
            <div class="summary-card">
                <h3>Space to Reclaim</h3>
                <div class="value size" id="totalSize">0 B</div>
            </div>
        </div>
        
        <div class="category-filters" id="categoryFilters"></div>
        
        <div class="locations-grid" id="locationsGrid">
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                </svg>
                <h3>Click "Scan System" to start</h3>
                <p>We'll find all cache and temporary files on your Mac</p>
            </div>
        </div>
    </div>
    
    <div class="progress-overlay" id="progressOverlay">
        <div class="progress-card">
            <div class="spinner"></div>
            <h3 id="progressText">Scanning...</h3>
            <p id="progressSub">Looking for cache files</p>
        </div>
    </div>
    
    <div class="toast" id="toast">
        <span id="toastIcon">✓</span>
        <span id="toastMessage"></span>
    </div>

    <script>
        let locations = [];
        let activeCategory = 'all';
        
        function humanSize(bytes) {
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let i = 0;
            while (bytes >= 1024 && i < units.length - 1) {
                bytes /= 1024;
                i++;
            }
            return bytes.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
        }
        
        function getSizeClass(bytes) {
            if (bytes > 1073741824) return 'huge';
            if (bytes > 104857600) return 'large';
            if (bytes > 10485760) return 'medium';
            return 'small';
        }
        
        function showProgress(text, sub) {
            document.getElementById('progressText').textContent = text;
            document.getElementById('progressSub').textContent = sub;
            document.getElementById('progressOverlay').classList.add('show');
        }
        
        function hideProgress() {
            document.getElementById('progressOverlay').classList.remove('show');
        }
        
        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            const icon = document.getElementById('toastIcon');
            const msg = document.getElementById('toastMessage');
            
            icon.textContent = type === 'success' ? '✓' : '✗';
            msg.textContent = message;
            toast.className = 'toast show ' + type;
            
            setTimeout(() => toast.classList.remove('show'), 3000);
        }
        
        async function startScan() {
            showProgress('Scanning...', 'Looking for cache files');
            document.getElementById('scanBtn').disabled = true;
            
            await fetch('/api/scan', { method: 'POST' });
            
            // Poll for completion
            const poll = async () => {
                const res = await fetch('/api/scan/status');
                const data = await res.json();
                
                if (data.complete) {
                    await loadLocations();
                    hideProgress();
                    document.getElementById('scanBtn').disabled = false;
                    showToast(`Found ${locations.length} locations with cached data`);
                } else {
                    setTimeout(poll, 500);
                }
            };
            poll();
        }
        
        async function loadLocations() {
            const res = await fetch('/api/locations');
            locations = await res.json();
            renderCategories();
            renderLocations();
            updateSummary();
        }
        
        function renderCategories() {
            const categories = ['all', ...new Set(locations.map(l => l.category))];
            const container = document.getElementById('categoryFilters');
            
            container.innerHTML = categories.map(cat => `
                <button class="category-btn ${cat === activeCategory ? 'active' : ''}" 
                        onclick="filterCategory('${cat}')">
                    ${cat === 'all' ? 'All' : cat}
                </button>
            `).join('');
        }
        
        function filterCategory(category) {
            activeCategory = category;
            renderCategories();
            renderLocations();
        }
        
        function renderLocations() {
            const container = document.getElementById('locationsGrid');
            const filtered = activeCategory === 'all' 
                ? locations 
                : locations.filter(l => l.category === activeCategory);
            
            if (filtered.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <h3>No items found</h3>
                        <p>Try a different category or scan again</p>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = filtered.map((loc, i) => `
                <div class="location-card ${loc.selected ? 'selected' : ''}" data-id="${loc.id}">
                    <div class="location-header">
                        <label class="checkbox-wrapper">
                            <input type="checkbox" ${loc.selected ? 'checked' : ''} 
                                   onchange="toggleLocation('${loc.id}')">
                            <div class="checkbox-custom"></div>
                        </label>
                        <div class="location-info">
                            <div class="location-name">
                                ${loc.name}
                                <span class="risk-badge risk-${loc.risk}">${loc.risk}</span>
                                <button class="hint-btn" onclick="toggleHint('${loc.id}')">?</button>
                            </div>
                            <div class="location-desc">${loc.description}</div>
                            <div class="location-path">${loc.path.replace('${location.pathname}', '~')}</div>
                        </div>
                        <div class="location-size ${getSizeClass(loc.size)}">${loc.size_human}</div>
                    </div>
                    <div class="hint-panel" id="hint-${loc.id}">
                        <div class="hint-section">
                            <h4>📖 What is this?</h4>
                            <p>${loc.hint}</p>
                        </div>
                        <div class="hint-section">
                            <h4>⚡ Impact of Cleaning</h4>
                            <p>${loc.impact}</p>
                        </div>
                    </div>
                </div>
            `).join('');
        }
        
        function toggleHint(id) {
            const panel = document.getElementById('hint-' + id);
            panel.classList.toggle('show');
        }
        
        function toggleLocation(id) {
            const loc = locations.find(l => l.id === id);
            if (loc) {
                loc.selected = !loc.selected;
                renderLocations();
                updateSummary();
            }
        }
        
        function selectAll() {
            locations.forEach(l => l.selected = true);
            renderLocations();
            updateSummary();
        }
        
        function selectNone() {
            locations.forEach(l => l.selected = false);
            renderLocations();
            updateSummary();
        }
        
        function updateSummary() {
            const selected = locations.filter(l => l.selected);
            const totalBytes = selected.reduce((sum, l) => sum + l.size, 0);
            
            document.getElementById('selectedCount').textContent = selected.length;
            document.getElementById('totalSize').textContent = humanSize(totalBytes);
            document.getElementById('cleanBtn').disabled = selected.length === 0;
        }
        
        async function cleanSelected() {
            const selected = locations.filter(l => l.selected);
            if (selected.length === 0) return;
            
            const totalSize = humanSize(selected.reduce((sum, l) => sum + l.size, 0));
            
            if (!confirm(`This will permanently delete ${selected.length} cache locations (${totalSize}).\\n\\nAre you sure?`)) {
                return;
            }
            
            showProgress('Cleaning...', 'Removing selected cache files');
            
            const res = await fetch('/api/clean', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: selected.map(l => l.id) })
            });
            
            const data = await res.json();
            const successCount = data.results.filter(r => r.success).length;
            
            hideProgress();
            showToast(`Cleaned ${successCount} of ${selected.length} locations`);
            
            // Re-scan
            startScan();
        }
    </script>
</body>
</html>
'''


# Create templates directory and save template
def setup_templates():
    template_dir = Path(__file__).parent / 'templates'
    template_dir.mkdir(exist_ok=True)
    (template_dir / 'index.html').write_text(HTML_TEMPLATE)


def open_browser():
    """Open browser after a short delay."""
    import time
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5050')


if __name__ == '__main__':
    setup_templates()
    
    print("\n" + "="*50)
    print("  Q-Cleaner Web Panel")
    print("  Open http://127.0.0.1:5050 in your browser")
    print("="*50 + "\n")
    
    # Open browser in background
    threading.Thread(target=open_browser, daemon=True).start()
    
    app.run(host='127.0.0.1', port=5050, debug=False)
