// Regression test for interrupted replies.
//
// Pressing the button mid-answer calls StreamResponser.stop(), but a playback
// loop parked on an await cannot be killed: it wakes afterwards and keeps
// walking the queue, which by then holds the *next* reply. On the device that
// showed up as the same sentence playing twice and out of order; here, with
// shorter clips, it shows up as the stale loop reaching its completion branch
// and wiping the new reply after one sentence. Both are the same fault.
//
// Run against the built output:  node scripts/test-interrupted-reply.js
// Expect PASS. Neutralise the generation check in StreamResponser and it fails.
const path = require("path");
const ROOT = path.resolve(__dirname, "..", "dist");
const audioPath = require.resolve(ROOT + "/device/audio.js");

let batch = "A";
const played = [];
require.cache[audioPath] = {
  id: audioPath, filename: audioPath, loaded: true, exports: {
    playAudioData: async (p) => {
      played.push(p.tag);
      await new Promise((r) => setTimeout(r, 150));   // a sentence takes time
    },
    stopPlaying: () => {},
  },
};

const { StreamResponser } = require(ROOT + "/core/StreamResponsor.js");
// tagged at synthesis time, so each clip carries the batch it belongs to
const r = new StreamResponser(async (text) => ({
  duration: 100, filePath: "/dev/null", tag: `${batch}:${text.trim()}`,
}));

const feed = async (sentences) => {
  for (const s of sentences) { r.partial(s); await new Promise((x) => setTimeout(x, 15)); }
  r.endPartial();
};

(async () => {
  await feed(["One. ", "Two. ", "Three. ", "Four. ", "Five. ", "Six. "]);
  await new Promise((res) => setTimeout(res, 400));     // batch A is playing
  const cut = played.length;

  r.stop();                                             // <- the button press
  batch = "B";
  await feed(["Alpha. ", "Beta. ", "Gamma. ", "Delta. "]);
  await new Promise((res) => setTimeout(res, 2500));

  const after = played.slice(cut);
  const leaked = after.filter((t) => t.startsWith("A:"));
  const dupes = after.filter((t, i) => after.indexOf(t) !== i);
  console.log("before interrupt:", played.slice(0, cut).join(" | ") || "(none)");
  console.log("after interrupt :", after.join(" | ") || "(none)");
  console.log("");
  console.log("old reply still playing after the press:", leaked.length, leaked.join(", "));
  console.log("sentences played more than once        :", dupes.length, dupes.join(", "));
  const expected = ["B:Alpha.", "B:Beta.", "B:Gamma.", "B:Delta."];
  const complete = after.length === expected.length &&
    expected.every((sentence, index) => after[index] === sentence);
  console.log("new reply played in full and in order  :", complete, `(${after.length}/4)`);
  const passed = leaked.length === 0 && dupes.length === 0 && complete;
  console.log(passed ? "\nPASS" : "\nFAIL");
  process.exitCode = passed ? 0 : 1;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
