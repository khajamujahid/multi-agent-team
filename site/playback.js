(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.chooseShownIteration = api.chooseShownIteration;
  root.playbackFinished = api.playbackFinished;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function chooseShownIteration(revealedIterations, pinnedIteration, followLatest) {
    if (!revealedIterations.length) return null;
    const latest = revealedIterations[revealedIterations.length - 1];
    const pinIsVisible = revealedIterations.indexOf(pinnedIteration) !== -1;
    if (followLatest || pinnedIteration == null || !pinIsVisible) return latest;
    return pinnedIteration;
  }

  function playbackFinished() {
    return { mode: "final", followLatest: true, pinnedIteration: null };
  }

  return { chooseShownIteration: chooseShownIteration, playbackFinished: playbackFinished };
});
