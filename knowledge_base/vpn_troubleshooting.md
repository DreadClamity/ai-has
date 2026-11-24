# VPN Troubleshooting Guide
Category: Network and Remote Access

## Overview
Acme Corp uses the GlobalConnect VPN client for remote access to internal systems. Sign-in requires your domain password and a code from your authenticator app.

## Before You Start
1. Confirm you can open a public website such as a news site without the VPN.
2. Close any other VPN or proxy software.
3. Make sure the GlobalConnect client is on the latest version shown in Software Center.

## Error: Authentication Failed
Check that your password has not expired and that you typed the newest 6-digit code. If codes keep failing, set your phone to automatic date and time, because wrong clock settings cause rejected codes. If the password was reset recently, wait 5 minutes and try again.

## Error: Connection Timed Out or Gateway Unreachable
Switch networks, for example from home Wi-Fi to a mobile hotspot. In the client, change the gateway from vpn-sg.acme.example to vpn-us.acme.example or the other way around. Some public and hotel networks block VPN traffic, so use a hotspot there.

## Connected But Internal Sites Will Not Open
Disconnect and reconnect the VPN. Then open Command Prompt and run ipconfig /flushdns. Try opening the site by its full address, for example intranet.acme.example.

## Slow VPN Connection
Close video streaming and large downloads. Use a wired connection or sit closer to the router. Restart the VPN client.

## Reinstalling the Client
Open Software Center, uninstall GlobalConnect VPN, restart the laptop, then install it again from Software Center.

## Escalation
If the problem remains after these steps, create a ticket for the Network team with the client version, the exact error message, the time it happened, and the network used.