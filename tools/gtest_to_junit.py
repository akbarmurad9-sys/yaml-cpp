#!/usr/bin/env python3
"""Merge GoogleTest XML shard reports into one strict JUnit XML file for Harness.

Fails closed: no input files, an unreadable file, or zero test cases is an error,
because a test stage that reports nothing must not look like a passing one.
"""
import argparse, glob, sys
import xml.etree.ElementTree as ET

def fail(msg):
    print(f"CONVERTER ERROR: {msg}")
    sys.exit(1)

ap = argparse.ArgumentParser()
ap.add_argument("inputs", nargs="+")
ap.add_argument("-o", "--output", required=True)
a = ap.parse_args()

files = sorted({f for pattern in a.inputs for f in glob.glob(pattern)})
if not files:
    fail("no GoogleTest XML files matched " + " ".join(a.inputs))

suites = {}
for path in files:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        fail(f"{path} is not valid XML: {e}")
    for ts in root.iter("testsuite"):
        bucket = suites.setdefault(ts.get("name", "unnamed"), [])
        for tc in ts.findall("testcase"):
            failures = tc.findall("failure")
            skipped = tc.find("skipped") is not None or tc.get("status") == "notrun" \
                or tc.get("result") in ("skipped", "suppressed")
            bucket.append({
                "classname": tc.get("classname") or ts.get("name", "unnamed"),
                "name": tc.get("name", "unnamed"),
                "time": tc.get("time", "0"),
                "failures": [(f.get("message", "failed"), (f.text or "").strip()) for f in failures],
                "skipped": skipped and not failures,
            })

total = sum(len(v) for v in suites.values())
if total == 0:
    fail("the reports contain zero test cases")

out = ET.Element("testsuites", name="googletest")
T = F = S = 0
tt = 0.0
for name, cases in sorted(suites.items()):
    n_f = sum(1 for c in cases if c["failures"])
    n_s = sum(1 for c in cases if c["skipped"])
    t = sum(float(c["time"] or 0) for c in cases)
    s = ET.SubElement(out, "testsuite", name=name, tests=str(len(cases)), failures=str(n_f),
                      errors="0", skipped=str(n_s), time=f"{t:.3f}")
    for c in cases:
        e = ET.SubElement(s, "testcase", classname=c["classname"], name=c["name"], time=c["time"])
        for msg, text in c["failures"]:
            fe = ET.SubElement(e, "failure", message=msg.splitlines()[0][:300] if msg else "failed", type="AssertionFailure")
            fe.text = text or msg
        if c["skipped"]:
            ET.SubElement(e, "skipped")
    T += len(cases); F += n_f; S += n_s; tt += t
out.set("tests", str(T)); out.set("failures", str(F)); out.set("errors", "0")
out.set("skipped", str(S)); out.set("time", f"{tt:.3f}")
ET.ElementTree(out).write(a.output, encoding="utf-8", xml_declaration=True)
print(f"Merged {len(files)} shard file(s): {T} tests, {F} failed, {S} skipped -> {a.output}")
