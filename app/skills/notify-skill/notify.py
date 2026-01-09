#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "httpx>=0.27.0",
# ]
# ///
"""
Prime Notify - Send push notifications to registered devices via Prime API

Usage:
    notify.py --title "Title" --body "Message"
    notify.py michaels-iphone --title "Title" --body "Message"
    notify.py iphone --title "Update" --body "New feature"
    notify.py --environment production --title "Alert" --body "Error" --priority high

Dependencies:
    - httpx>=0.27.0 (auto-managed by uv)
"""

import argparse
import json
import os
import sys
from typing import Optional

import httpx




def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Send push notifications to registered devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  notify.py --title "Done" --body "Processing complete"
  notify.py michaels-iphone --title "Test" --body "Hello"
  notify.py iphone --title "Update" --body "New feature"
  notify.py iphone,mac --title "Multi" --body "All Apple devices"
  notify.py --environment production --title "Alert" --body "Error" --priority high
        """
    )
    parser.add_argument(
        "device_filter",
        nargs="?",
        help="Device name, type, or comma-separated list (optional, default: all devices)"
    )
    parser.add_argument("--title", required=True, help="Notification title")
    parser.add_argument("--body", required=True, help="Notification body")
    parser.add_argument(
        "--priority",
        choices=["high", "normal"],
        default="normal",
        help="Notification priority (default: normal)"
    )
    parser.add_argument(
        "--environment",
        choices=["development", "production"],
        help="Filter by device environment"
    )
    parser.add_argument("--data", help="Custom data as JSON string")
    parser.add_argument("--badge", type=int, help="Badge count")
    parser.add_argument("--sound", default="default", help="Sound name (default: default)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    return parser.parse_args()


def load_config() -> dict:
    """Load configuration from environment variables

    Returns:
        dict with keys: api_url, api_token

    Environment variables:
        - PRIME_API_URL: API endpoint (required)
        - PRIME_API_TOKEN: API authentication token (required)
    """
    api_url = os.environ.get("PRIME_API_URL")
    api_token = os.environ.get("PRIME_API_TOKEN")

    # Validate required config
    missing = []
    if not api_url:
        missing.append("PRIME_API_URL")
    if not api_token:
        missing.append("PRIME_API_TOKEN")

    if missing:
        print("Error: Required environment variables not set:", file=sys.stderr)
        for var in missing:
            print(f"  - {var}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Set the required environment variables:", file=sys.stderr)
        print("  export PRIME_API_URL='your-api-url'", file=sys.stderr)
        print("  export PRIME_API_TOKEN='your-api-token'", file=sys.stderr)
        sys.exit(3)

    return {
        "api_url": api_url,
        "api_token": api_token,
    }


def send_notification_via_api(
    api_url: str,
    api_token: str,
    title: str,
    body: str,
    device_filter: Optional[str] = None,
    environment: Optional[str] = None,
    priority: str = "normal",
    sound: str = "default",
    badge: Optional[int] = None,
    data: Optional[dict] = None,
    verbose: bool = False,
) -> dict:
    """Send notification via Prime API

    Args:
        api_url: Base URL of Prime API
        api_token: API authentication token
        title: Notification title
        body: Notification body
        device_filter: Optional device name/type filter
        environment: Optional environment filter
        priority: Notification priority (high/normal)
        sound: Notification sound
        badge: Optional badge count
        data: Optional custom data dict
        verbose: Show detailed output

    Returns:
        API response dict

    Raises:
        SystemExit on error
    """
    endpoint = f"{api_url}/api/v1/notifications/send"

    # Build request payload
    payload = {
        "title": title,
        "body": body,
        "priority": priority,
        "sound": sound,
    }

    if device_filter:
        payload["device_filter"] = device_filter

    if environment:
        payload["environment"] = environment

    if badge is not None:
        payload["badge"] = badge

    if data:
        payload["data"] = data

    if verbose:
        print(f"Sending notification to {endpoint}...")
        print(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        response = httpx.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        if verbose:
            print(f"Response status: {response.status_code}")

        # Handle non-2xx responses
        if response.status_code == 401:
            print("Error: Invalid API token", file=sys.stderr)
            sys.exit(3)
        elif response.status_code == 503:
            print("Error: Push notifications not enabled on server", file=sys.stderr)
            sys.exit(3)
        elif response.status_code >= 400:
            error_msg = response.text
            try:
                error_data = response.json()
                error_msg = error_data.get("detail", error_msg)
            except Exception:
                pass
            print(f"Error: API request failed: {error_msg}", file=sys.stderr)
            sys.exit(2)

        # Parse successful response
        result = response.json()
        return result

    except httpx.TimeoutException:
        print(f"Error: Request timed out connecting to {api_url}", file=sys.stderr)
        sys.exit(2)
    except httpx.ConnectError:
        print(f"Error: Could not connect to {api_url}", file=sys.stderr)
        print("Check that the Prime server is running and accessible", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: Failed to send notification: {e}", file=sys.stderr)
        sys.exit(2)


def main():
    """Main function"""
    args = parse_args()

    # Load configuration
    config = load_config()

    # Parse custom data if provided
    custom_data = None
    if args.data:
        try:
            custom_data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --data: {e}", file=sys.stderr)
            sys.exit(3)

    # Send notification via API
    if not args.verbose and not args.json:
        print(f"Sending notification...")

    result = send_notification_via_api(
        api_url=config["api_url"],
        api_token=config["api_token"],
        title=args.title,
        body=args.body,
        device_filter=args.device_filter,
        environment=args.environment,
        priority=args.priority,
        sound=args.sound,
        badge=args.badge,
        data=custom_data,
        verbose=args.verbose,
    )

    # Output results
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            if not args.verbose:
                print(f"✓ Sent to {result['sent']} device(s)")
        else:
            if not args.verbose:
                if result["sent"] > 0:
                    print(f"✓ Sent to {result['sent']} device(s)")
                if result["failed"] > 0:
                    print(f"✗ Failed to send to {result['failed']} device(s)")

        if result.get("invalid_tokens_removed", 0) > 0:
            print(f"⚠ Removed {result['invalid_tokens_removed']} invalid token(s)")

        if args.verbose:
            print(f"\nDevice results:")
            for device in result.get("devices", []):
                status = device["status"]
                name = device["name"]
                if status == "sent":
                    print(f"  ✓ {name}")
                else:
                    error = device.get("error", "unknown error")
                    print(f"  ✗ {name}: {error}")

    # Exit with appropriate code
    sent = result["sent"]
    failed = result["failed"]
    total = sent + failed

    if failed == total and total > 0:
        sys.exit(2)  # Complete failure
    elif failed > 0:
        sys.exit(1)  # Partial failure
    else:
        sys.exit(0)  # Success


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(3)
