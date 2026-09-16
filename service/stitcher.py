import re
from typing import List

# Patterns that clearly denote continuation frames of an error or stack trace
TRACE_LINE_PATTERNS = [
    re.compile(r'^\s*at\s+'),                  # Node/Java: at Function.name (file.js:12:3)
    re.compile(r'^\s*File\s+"'),               # Python: File "app.py", line 12
    re.compile(r'^\s*Caused by:'),             # Java/JVM: Caused by:
    re.compile(r'^\s*Read more:\s+https?://'), # Next.js error link
    re.compile(r'^\s*\.{3}\s+\d+\s+more'),     # JVM: ... 24 more
    re.compile(r'^\s*(raise|return)\s+'),      # Python traceback code line
    re.compile(r'^\s+ignore-listed frames'),   # Next.js / Chrome: ignore-listed frames
]

PYTHON_EXCEPTION_PATTERN = re.compile(r'^[a-zA-Z_]\w*(?:Error|Exception|Warning|Fault|Interrupt|Panic|Crash):\s*')

def is_continuation_line(line: str, current_log: List[str] = None) -> bool:
    """Check if a log line is a continuation/stack-trace frame of the previous line."""
    stripped = line.strip()
    if not stripped:
        return False
    
    # Check explicit trace patterns
    for pat in TRACE_LINE_PATTERNS:
        if pat.search(line):
            return True
            
    # Check if indented with 2+ spaces or a tab, and doesn't look like a new timestamped log
    if line.startswith('\t') or line.startswith('   '):
        # If it starts with an ISO timestamp or syslog date, it's NOT a continuation
        if re.match(r'^\s*(?:\d{4}-\d{2}-\d{2}|\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})', line):
            return False
        return True
        
    # If an active traceback is in progress, the terminating exception line is part of the trace
    if current_log and any("Traceback" in l or 'File "' in l for l in current_log):
        if PYTHON_EXCEPTION_PATTERN.match(line):
            return True

    return False

def stitch_multiline_logs(lines: List[str]) -> List[str]:
    """
    Stitches multi-line stack traces (Node.js, Python, Java) into single log entries.
    Preserves single-line independent logs as-is.
    """
    if not lines:
        return []
        
    stitched: List[str] = []
    current_log: List[str] = []
    
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line:
            continue
            
        if is_continuation_line(line, current_log) and current_log:
            current_log.append(line.strip())
        else:
            if current_log:
                stitched.append("\n".join(current_log))
            current_log = [line]
            
    if current_log:
        stitched.append("\n".join(current_log))
        
    return stitched
