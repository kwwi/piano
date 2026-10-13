"""Stand-in for m2s_worker/worker.py speaking the same JSON-lines protocol.

Writes a fixed one-part grand-staff MusicXML per request. Behaviour is selected
with ``FAKE_M2S_MODE``:

* ``ok``          — normal operation (default)
* ``not_ready``   — reports ``ready: false`` and exits
* ``hang``        — never answers conversion requests
* ``crash_once``  — exits on the first request (marker file ``FAKE_M2S_MARKER``)
"""
import json
import os
import sys
import time
from pathlib import Path

XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>{name}</part-name>
      <score-instrument id="P1-I1"><instrument-name>Piano</instrument-name></score-instrument>
    </score-part>
  </part-list>
  <part id="P1">
{measures}
  </part>
</score-partwise>
"""

MEASURE = """    <measure number="{n}">{attrs}
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>5</voice><type>whole</type><staff>2</staff></note>
    </measure>"""

ATTRS = """
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time>
        <staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>"""


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    mode = os.environ.get("FAKE_M2S_MODE", "ok")
    if mode == "not_ready":
        emit({"ready": False, "error": "checkpoint missing"})
        return 1
    emit({"ready": True, "device": "cpu"})
    for line in sys.stdin:
        req = json.loads(line)
        rid = req.get("id")
        if req.get("cmd") == "ping":
            emit({"id": rid, "ok": True})
            continue
        if req.get("cmd") == "exit":
            emit({"id": rid, "ok": True})
            return 0
        if mode == "hang":
            time.sleep(3600)
        if mode == "crash_once":
            marker = Path(os.environ["FAKE_M2S_MARKER"])
            if not marker.exists():
                marker.write_text("crashed")
                sys.exit(3)
        # Measure count derives from the MIDI size so different inputs differ.
        n_measures = int(req.get("measures") or 2)
        try:
            import pretty_midi

            pm = pretty_midi.PrettyMIDI(req["midi"])
            n_measures = max(1, int(pm.get_end_time() // 2) + 1)
        except Exception:
            pass
        measures = "\n".join(
            MEASURE.format(n=i + 1, attrs=ATTRS if i == 0 else "") for i in range(n_measures)
        )
        Path(req["out"]).write_text(
            XML.format(name=req.get("name") or "Piano", measures=measures), encoding="utf-8"
        )
        with open(os.environ.get("FAKE_M2S_LOG", os.devnull), "a", encoding="utf-8") as log:
            log.write(json.dumps(req) + "\n")
        emit({"id": rid, "ok": True, "notes": 1})
    return 0


if __name__ == "__main__":
    sys.exit(main())
