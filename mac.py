#!/usr/bin/env python3
"""
Q-Cleaner for macOS
A Python-based cache and temp file cleaner with interactive UI
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

# Check for required packages
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import box
except ImportError:
    print("Installing required package: rich")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import box

console = Console()


class SizeCategory(Enum):
    TINY = "tiny"      # < 10MB
    SMALL = "small"    # 10MB - 100MB
    MEDIUM = "medium"  # 100MB - 1GB
    LARGE = "large"    # > 1GB


@dataclass
class CacheLocation:
    path: str
    description: str
    category: str
    size: int = 0
    size_human: str = "0B"
    selected: bool = False
    exists: bool = False


def get_home() -> str:
    """Get user home directory."""
    return str(Path.home())


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human readable format."""
    if size_bytes < 0:
        return "0B"
    
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if abs(size_bytes) < 1024.0:
            if unit == 'B':
                return f"{size_bytes}{unit}"
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}P"


def get_size_category(size_bytes: int) -> SizeCategory:
    """Get size category for color coding."""
    if size_bytes > 1073741824:  # > 1GB
        return SizeCategory.LARGE
    elif size_bytes > 104857600:  # > 100MB
        return SizeCategory.MEDIUM
    elif size_bytes > 10485760:  # > 10MB
        return SizeCategory.SMALL
    return SizeCategory.TINY


def get_directory_size(path: str) -> int:
    """Get size of a directory in bytes."""
    try:
        # Use du command for speed on macOS
        result = subprocess.run(
            ['du', '-sk', path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            size_kb = int(result.stdout.split()[0])
            return size_kb * 1024
    except (subprocess.TimeoutExpired, ValueError, IndexError, FileNotFoundError):
        pass
    
    # Fallback to Python method
    total_size = 0
    try:
        path_obj = Path(path)
        if path_obj.is_file():
            return path_obj.stat().st_size
        for entry in path_obj.rglob('*'):
            try:
                if entry.is_file():
                    total_size += entry.stat().st_size
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return total_size


def get_cache_locations() -> List[CacheLocation]:
    """Get all cache locations to scan."""
    home = get_home()
    
    locations = [
        # System Caches
        CacheLocation(f"{home}/Library/Caches", "User Application Caches", "System"),
        CacheLocation("/Library/Caches", "System Application Caches", "System"),
        CacheLocation("/System/Library/Caches", "macOS System Caches", "System"),
        
        # Developer Tools - Xcode
        CacheLocation(f"{home}/Library/Developer/Xcode/DerivedData", "Xcode Build Data", "Developer"),
        CacheLocation(f"{home}/Library/Developer/Xcode/Archives", "Xcode Archives", "Developer"),
        CacheLocation(f"{home}/Library/Developer/Xcode/iOS DeviceSupport", "iOS Device Support", "Developer"),
        CacheLocation(f"{home}/Library/Developer/CoreSimulator/Caches", "Simulator Caches", "Developer"),
        CacheLocation(f"{home}/Library/Developer/CoreSimulator/Devices", "Simulator Devices", "Developer"),
        CacheLocation(f"{home}/Library/Caches/com.apple.dt.Xcode", "Xcode Cache", "Developer"),
        
        # Developer Tools - Build Systems
        CacheLocation(f"{home}/.gradle/caches", "Gradle Build Cache", "Developer"),
        CacheLocation(f"{home}/.m2/repository", "Maven Repository Cache", "Developer"),
        CacheLocation(f"{home}/.cargo/registry", "Rust Cargo Registry", "Developer"),
        CacheLocation(f"{home}/.rustup/toolchains", "Rust Toolchains", "Developer"),
        
        # Package Managers
        CacheLocation(f"{home}/.pub-cache", "Flutter/Dart Pub Cache", "Packages"),
        CacheLocation(f"{home}/.npm/_cacache", "NPM Cache", "Packages"),
        CacheLocation(f"{home}/.npm/_logs", "NPM Logs", "Packages"),
        CacheLocation(f"{home}/.yarn/cache", "Yarn Cache", "Packages"),
        CacheLocation(f"{home}/.pnpm-store", "PNPM Store", "Packages"),
        CacheLocation(f"{home}/.cache/pip", "Python Pip Cache", "Packages"),
        CacheLocation(f"{home}/.cache/pypoetry", "Python Poetry Cache", "Packages"),
        CacheLocation(f"{home}/.gem/ruby", "Ruby Gems", "Packages"),
        CacheLocation(f"{home}/go/pkg/mod/cache", "Go Module Cache", "Packages"),
        CacheLocation(f"{home}/.cocoapods/repos", "CocoaPods Repos", "Packages"),
        
        # General Caches
        CacheLocation(f"{home}/.cache", "General User Cache", "General"),
        CacheLocation(f"{home}/Library/Caches/Homebrew", "Homebrew Downloads", "General"),
        CacheLocation("/usr/local/Homebrew/Library/Taps", "Homebrew Taps", "General"),
        
        # Browser Caches
        CacheLocation(f"{home}/Library/Caches/com.apple.Safari", "Safari Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Safari/LocalStorage", "Safari LocalStorage", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/Google/Chrome/Default/Cache", "Chrome Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/Google/Chrome/Default/Code Cache", "Chrome Code Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage", "Chrome SW Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/com.microsoft.Edge", "Edge Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/com.brave.Browser", "Brave Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/com.operasoftware.Opera", "Opera Cache", "Browsers"),
        CacheLocation(f"{home}/Library/Caches/Firefox", "Firefox Cache", "Browsers"),
        
        # Temp Files
        CacheLocation("/tmp", "System Temp Files", "Temp"),
        CacheLocation(f"{home}/Library/Temporary Items", "User Temp Items", "Temp"),
        CacheLocation("/var/folders", "System Cache Folders", "Temp"),
        CacheLocation("/private/var/tmp", "Private Temp", "Temp"),
        
        # Logs
        CacheLocation("/var/log", "System Logs", "Logs"),
        CacheLocation(f"{home}/Library/Logs", "User Application Logs", "Logs"),
        CacheLocation("/Library/Logs", "Library Logs", "Logs"),
        
        # Thumbnail/Preview Caches
        CacheLocation(f"{home}/Library/Caches/com.apple.thumbnail.cache", "Thumbnail Cache", "System"),
        CacheLocation(f"{home}/Library/Caches/com.apple.QuickLook.thumbnailcache", "QuickLook Cache", "System"),
        
        # HTTP/Cookies
        CacheLocation(f"{home}/Library/HTTPStorages", "HTTP Storage", "System"),
        CacheLocation(f"{home}/Library/Cookies", "Cookies", "System"),
        
        # Application Caches
        CacheLocation(f"{home}/Library/Application Support/Code/CachedData", "VS Code Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/Code/CachedExtensions", "VS Code Extensions Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/Slack/Cache", "Slack Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/Slack/Service Worker/CacheStorage", "Slack SW Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/discord/Cache", "Discord Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/Spotify/PersistentCache", "Spotify Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/Cursor/CachedData", "Cursor Cache", "Applications"),
        CacheLocation(f"{home}/Library/Application Support/JetBrains", "JetBrains Cache", "Applications"),
        
        # Docker
        CacheLocation(f"{home}/Library/Containers/com.docker.docker/Data/vms", "Docker VM Data", "Docker"),
        CacheLocation(f"{home}/.docker/buildx", "Docker Buildx Cache", "Docker"),
        CacheLocation(f"{home}/Library/Containers/com.docker.docker/Data/docker/volumes", "Docker Volumes", "Docker"),
        
        # Cloud Caches
        CacheLocation(f"{home}/Library/Caches/CloudKit", "CloudKit Cache", "Cloud"),
        CacheLocation(f"{home}/Library/Caches/com.apple.iCloudDrive", "iCloud Cache", "Cloud"),
        
        # Mail
        CacheLocation(f"{home}/Library/Caches/com.apple.mail", "Mail Cache", "System"),
        
        # iOS Backups (WARNING: Large!)
        CacheLocation(f"{home}/Library/Application Support/MobileSync/Backup", "iOS Backups (LARGE!)", "Backups"),
    ]
    
    return locations


def scan_sandboxed_apps(home: str) -> List[CacheLocation]:
    """Scan sandbox container caches."""
    locations = []
    containers_path = Path(f"{home}/Library/Containers")
    
    if containers_path.exists():
        for container in containers_path.iterdir():
            cache_path = container / "Data" / "Library" / "Caches"
            if cache_path.exists() and cache_path.is_dir():
                app_name = container.name.split('.')[-1] if '.' in container.name else container.name
                locations.append(CacheLocation(
                    str(cache_path),
                    f"{app_name} Container Cache",
                    "Containers"
                ))
    
    return locations


def scan_locations(locations: List[CacheLocation]) -> List[CacheLocation]:
    """Scan all locations and get their sizes."""
    valid_locations = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Scanning..."),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("", total=len(locations))
        
        for loc in locations:
            progress.update(task, advance=1, description=f"[dim]{loc.description[:30]}...[/dim]")
            
            path = Path(loc.path)
            if path.exists():
                loc.exists = True
                loc.size = get_directory_size(loc.path)
                loc.size_human = human_readable_size(loc.size)
                
                if loc.size > 0:
                    loc.selected = True  # Pre-select non-zero items
                    valid_locations.append(loc)
    
    return valid_locations


def get_size_color(loc: CacheLocation) -> str:
    """Get color based on size."""
    category = get_size_category(loc.size)
    if category == SizeCategory.LARGE:
        return "bold red"
    elif category == SizeCategory.MEDIUM:
        return "yellow"
    elif category == SizeCategory.SMALL:
        return "green"
    return "dim"


def display_menu(locations: List[CacheLocation]) -> None:
    """Display the interactive selection menu."""
    console.clear()
    
    # Header
    console.print(Panel(
        "[bold cyan]macOS Cache & Temp File Cleaner[/bold cyan]\n"
        "[dim]Q-Cleaner v2.0[/dim]",
        box=box.DOUBLE,
        border_style="cyan"
    ))
    
    console.print()
    console.print("[yellow]Commands: [bold]number[/bold]=toggle, [bold]a[/bold]=all, [bold]n[/bold]=none, [bold]d[/bold]=delete, [bold]q[/bold]=quit[/yellow]")
    console.print()
    
    # Create table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("", width=3)  # Checkbox
    table.add_column("Size", width=10, justify="right")
    table.add_column("Location", width=45)
    table.add_column("Description", style="cyan")
    
    for i, loc in enumerate(locations):
        idx = str(i + 1)
        checkbox = "[green]✓[/green]" if loc.selected else "[ ]"
        size_color = get_size_color(loc)
        
        # Shorten path for display
        display_path = loc.path.replace(get_home(), "~")
        if len(display_path) > 43:
            display_path = display_path[:40] + "..."
        
        table.add_row(
            idx,
            checkbox,
            f"[{size_color}]{loc.size_human}[/{size_color}]",
            display_path,
            loc.description
        )
    
    console.print(table)
    
    # Summary
    selected_count = sum(1 for loc in locations if loc.selected)
    total_size = sum(loc.size for loc in locations if loc.selected)
    
    console.print()
    console.print(Panel(
        f"[bold]Selected:[/bold] [green]{selected_count}[/green] items | "
        f"[bold]Total size to clean:[/bold] [bold red]{human_readable_size(total_size)}[/bold red]",
        box=box.SIMPLE
    ))


def clear_location(loc: CacheLocation) -> tuple[bool, str]:
    """Clear a single location."""
    try:
        path = Path(loc.path)
        if path.is_dir():
            # Clear contents but keep directory
            for item in path.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except (PermissionError, OSError) as e:
                    pass  # Skip items we can't delete
            return True, "Cleared"
        elif path.is_file():
            path.unlink()
            return True, "Deleted"
        return False, "Not found"
    except PermissionError:
        return False, "Permission denied"
    except OSError as e:
        return False, str(e)


def clear_selected(locations: List[CacheLocation]) -> None:
    """Clear all selected locations."""
    selected = [loc for loc in locations if loc.selected]
    
    if not selected:
        console.print("[yellow]No items selected![/yellow]")
        return
    
    console.print()
    console.print("[bold red]Starting cleanup...[/bold red]")
    console.print()
    
    cleared = 0
    failed = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]Cleaning..."),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("", total=len(selected))
        
        for loc in selected:
            progress.update(task, advance=1)
            success, message = clear_location(loc)
            
            display_path = loc.path.replace(get_home(), "~")
            if success:
                console.print(f"  [green]✓[/green] {display_path}")
                cleared += 1
            else:
                console.print(f"  [red]✗[/red] {display_path} - {message}")
                failed += 1
    
    console.print()
    console.print(Panel(
        f"[bold green]Cleanup complete![/bold green]\n"
        f"Cleared: [green]{cleared}[/green] locations\n"
        f"{'Failed: [red]' + str(failed) + '[/red] locations (may require sudo)' if failed > 0 else ''}",
        box=box.ROUNDED,
        border_style="green"
    ))
    
    console.print()
    console.print("[yellow]Don't forget to empty the Trash to fully reclaim space![/yellow]")
    console.print("[dim]You may also want to run: sudo periodic daily weekly monthly[/dim]")


def main():
    """Main function."""
    console.clear()
    
    # Header
    console.print(Panel(
        "[bold cyan]macOS Cache & Temp File Cleaner[/bold cyan]\n"
        "[dim]Q-Cleaner v2.0[/dim]",
        box=box.DOUBLE,
        border_style="cyan"
    ))
    
    console.print()
    console.print("[yellow]Scanning cache and temp file locations...[/yellow]")
    console.print()
    
    # Get and scan locations
    locations = get_cache_locations()
    valid_locations = scan_locations(locations)
    
    if not valid_locations:
        console.print("[green]No cache files found to clean![/green]")
        return
    
    console.print(f"[green]Found {len(valid_locations)} locations with cache/temp data.[/green]")
    console.print()
    
    # Scan sandboxed apps
    console.print("[yellow]Scanning sandboxed app caches...[/yellow]")
    home = get_home()
    sandbox_locations = scan_sandboxed_apps(home)
    if sandbox_locations:
        sandbox_valid = scan_locations(sandbox_locations)
        valid_locations.extend(sandbox_valid)
    
    console.print(f"[green]Scan complete! Found {len(valid_locations)} locations total.[/green]")
    
    import time
    time.sleep(1)
    
    # Interactive loop
    while True:
        display_menu(valid_locations)
        
        try:
            choice = Prompt.ask("[bold]Enter choice[/bold]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled. No files were deleted.[/yellow]")
            break
        
        choice = choice.strip().lower()
        
        if choice == 'q':
            console.print("[yellow]Cancelled. No files were deleted.[/yellow]")
            break
        
        elif choice == 'a':
            for loc in valid_locations:
                loc.selected = True
        
        elif choice == 'n':
            for loc in valid_locations:
                loc.selected = False
        
        elif choice == 'd':
            selected_count = sum(1 for loc in valid_locations if loc.selected)
            if selected_count == 0:
                console.print("[yellow]No items selected![/yellow]")
                import time
                time.sleep(1)
                continue
            
            console.print()
            console.print("[bold red]WARNING: This will permanently delete the selected cache files![/bold red]")
            
            if Confirm.ask("Are you sure you want to proceed?", default=False):
                clear_selected(valid_locations)
                input("\nPress Enter to exit...")
                break
        
        elif choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(valid_locations):
                idx = num - 1
                valid_locations[idx].selected = not valid_locations[idx].selected
        
        # Handle range input like "1-5"
        elif '-' in choice:
            try:
                start, end = choice.split('-')
                start, end = int(start), int(end)
                if 1 <= start <= end <= len(valid_locations):
                    for i in range(start - 1, end):
                        valid_locations[i].selected = not valid_locations[i].selected
            except ValueError:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
