## Date: 18 June, 2026

## Polling Rate Results
interval=1.0s  avg_cpu=6.2%  avg_rss=14.7MB
interval=5.0s  avg_cpu=1.24%  avg_rss=14.73MB
interval=15.0s  avg_cpu=0.44%  avg_rss=14.74MB

## Context
The collector reads /proc/stat, /proc/meminfo, /proc/diskstats, /proc/net/dev,
and per-PID /proc/[pid]/stat on every cycle. Each cycle costs real CPU.

These are the CPU consumptions percentages alongside memory usage across 3 different polling intervals. The most optimal interval is 5.0s as the CPU usage is slightly >1% and the RSS (Resident Set Size - The physical memory that the process holds) iso optimal. The 1.0s interval fails the observer effect test, as it is consuming 6.2% CPU just to run. 

On the other hand, while the 15.0s intervals looks very optimal, the time range is too much for a process to spike and return to normal, which negates the premise of monitoring the data.  