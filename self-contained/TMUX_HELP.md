=========================================
📌 TMUX SESSION MANAGEMENT GUIDE
=========================================

Your monitor is running in tmux session: 'monitor'

🔑 ESSENTIAL COMMANDS:
----------------------
• DETACH (leave running):     Ctrl+B then D
• REATTACH to session:        tmux attach -t monitor
• LIST all sessions:          tmux ls
• KILL the monitor:           tmux kill-session -t monitor

📜 WHILE IN THE SESSION:
------------------------
• SCROLL UP/DOWN:             Ctrl+B then [
  - Use arrow keys or Page Up/Down to scroll
  - Press Q to exit scroll mode
• STOP the monitor:           Ctrl+C
• DETACH and keep running:    Ctrl+B then D

🔄 IF YOU ACCIDENTALLY EXIT:
-----------------------------
1. Check if still running:    tmux ls
2. Reattach to monitor:       tmux attach -t monitor
3. If session is dead, run the installer again

💡 COMMON SCENARIOS:
--------------------
• Lost SSH connection?        Monitor keeps running!
                             Just reattach: tmux attach -t monitor

• Want to check status?       tmux attach -t monitor
                             Then Ctrl+B, D to detach

• Need to restart fresh?      tmux kill-session -t monitor
                             Then run installer again

• Multiple monitors?          Use different session names:
                             tmux new -s monitor2 "/tmp/self_monitor.sh"

📊 VIEW MONITOR STATUS FILES:
------------------------------
• Current metrics:            cat /tmp/monitor_counter.json
• Configuration:              cat /tmp/monitor_config.json

=========================================