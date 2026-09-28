import json
import time
import urllib.request

custom_resume = b"""Kosal Vong
Phnom Penh, Cambodia
Bachelor of IT from Western University, 2023
Experience:
- Intern Web Developer at KhmerTech (6 months): Developed Vue.js frontend interfaces
- Project: Built a Delivery Tracker using Node.js and MongoDB
"""

custom_jd = """Vue.js Frontend Developer
Location: Phnom Penh
Requirements:
- Proven experience with Vue.js or similar modern frontend frameworks
- Understanding of RESTful APIs
- Degree in Computer Science or Information Technology
"""

boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = (
    b"--" + boundary.encode() + b"\r\n"
    b'Content-Disposition: form-data; name="file"; filename="kosal_resume.pdf"\r\n'
    b"Content-Type: application/pdf\r\n\r\n"
    b"%PDF-1.4\n" + custom_resume + b"\r\n"
    b"--" + boundary.encode() + b"--\r\n"
)

# 1. Upload resume
req = urllib.request.Request(
    "http://localhost:8000/api/resumes",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
with urllib.request.urlopen(req) as resp:
    resume_id = json.loads(resp.read().decode())["resume_id"]
print("Uploaded Resume ID:", resume_id)

# 2. Upload job
req_job = urllib.request.Request(
    "http://localhost:8000/api/jobs",
    data=json.dumps({"text": custom_jd}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req_job) as resp:
    job_id = json.loads(resp.read().decode())["job_id"]
print("Created Job ID:", job_id)

# 3. Create analysis
req_analysis = urllib.request.Request(
    "http://localhost:8000/api/analyses",
    data=json.dumps({"resume_id": resume_id, "job_id": job_id, "country": "KH"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req_analysis) as resp:
    analysis_id = json.loads(resp.read().decode())["analysis_id"]
print("Created Analysis ID:", analysis_id)

# 4. Poll until complete
for i in range(20):
    time.sleep(2)
    with urllib.request.urlopen(f"http://localhost:8000/api/analyses/{analysis_id}") as resp:
        data = json.loads(resp.read().decode())
        print(f"Poll {i+1}: status={data['status']}, stage={data.get('stage')}")
        if data["status"] == "done":
            m = data["match"]
            print("\n=== LIVE MATCH COMPLETED ===")
            print("Job Title:", m.get("job", {}).get("title"))
            print("Candidate Summary:", m.get("resume", {}).get("candidate_summary"))
            print("Coverage Score:", m.get("coverage_score"))
            print("Realism Verdict:", m.get("realism_verdict"))
            print("Verdicts count:", len(m.get("results", [])))
            for r in m.get("results", []):
                print(f" - [{r.get('verdict')}] req {r.get('requirement_id')}: {r.get('reasoning')}")
            break
