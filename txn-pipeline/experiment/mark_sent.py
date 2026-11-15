import fcntl
import json
import sys

with open("trials.lock", "w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    d = json.load(open("trials.json"))
    d["trials"][sys.argv[1]]["rounds"][-1]["feedback_sent_at"] = int(sys.argv[2])
    json.dump(d, open("trials.json", "w"), indent=2)
