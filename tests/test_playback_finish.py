import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_playback_finish_selects_the_final_green_suite():
    script = r"""
const assert = require("assert");
const { chooseShownIteration, playbackFinished } = require(process.argv[1]);

assert.strictEqual(chooseShownIteration([1], null, true), 1);
assert.strictEqual(chooseShownIteration([1, 2], 1, false), 1);

let pinned = null;
let follow = true;
for (const revealed of [[1], [1, 2]]) {
  pinned = chooseShownIteration(revealed, pinned, follow);
}
assert.strictEqual(pinned, 2);

const done = playbackFinished();
assert.deepStrictEqual(done, { mode: "final", followLatest: true, pinnedIteration: null });
assert.strictEqual(chooseShownIteration([1, 2], 1, done.followLatest), 2);
assert.strictEqual(chooseShownIteration([1, 2], done.pinnedIteration, done.followLatest), 2);
"""
    completed = subprocess.run(
        ["node", "-e", script, str(ROOT / "site" / "playback.js")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert 'src="playback.js"' in page
    assert "enterFinishedPlayback()" in page
    assert "followLatest = false" in page
