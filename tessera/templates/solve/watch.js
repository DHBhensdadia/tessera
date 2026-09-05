// Live progress, over the same SSE endpoint the native panel will use.
//
// The page underneath this is complete without it: the server renders the current status and
// refreshes itself, so a browser with scripting off loses the curve and nothing else. What
// this adds is a page that moves without being discarded four times a minute.
//
// **No template expressions in this file, ever.** Starlette builds its Jinja environment with
// `select_autoescape()`, which escapes .html and does not escape .js — so a variable written
// here would come out raw inside a <script> block while the same value two lines up in the
// page came out escaped. Everything this needs arrives on data- attributes of #solve, which
// are autoescaped because they live in the HTML.
//
// A test asserts the rule by looking for Jinja's delimiters in this file. Writing one in this
// comment to illustrate it is not safe either: an include is rendered, so the example would
// be substituted. That is how the first draft of this paragraph was caught.

(function () {
  var panel = document.getElementById("solve");
  if (!panel || typeof EventSource === "undefined") return;

  var out = {
    phase: document.getElementById("phase"),
    elapsed: document.getElementById("elapsed"),
    penalty: document.getElementById("penalty"),
    bound: document.getElementById("bound"),
    solutions: document.getElementById("solutions"),
    breakdown: document.getElementById("breakdown"),
    curve: document.getElementById("curve"),
    line: document.getElementById("curve-line"),
    headline: document.getElementById("headline"),
    explanation: document.getElementById("explanation"),
    phrasing: document.getElementById("phrasing"),
  };
  var showing = null;

  // Points collected since this page connected — not since the solve began. The wire carries
  // no trajectory (#306) and widening SolveStatus to carry one was refused, so a reload
  // honestly starts the curve again rather than pretending to know what it missed.
  var seen = [];
  var stream = new EventSource(panel.dataset.stream);

  function number(value) {
    return value === null || value === undefined ? "—" : String(value);
  }

  function words(rule) {
    var said = rule.replace(/_/g, " ");
    return said.charAt(0).toUpperCase() + said.slice(1);
  }

  // Nothing is drawn until there is a descent to draw. A term can hold one score for twenty
  // seconds — comp02 under Tessera's defaults does — and a flat line along the bottom of an
  // empty box says less than no box at all while taking up more room. The elapsed clock is
  // what shows the page is alive through that; this shows the shape of the fall.
  function draw() {
    var worst = seen[0][1];
    var best = seen[seen.length - 1][1];
    var drop = worst - best;
    if (seen.length < 2 || drop <= 0) return;

    var span = seen[seen.length - 1][0] || 1;
    var points = seen.map(function (point) {
      var x = (point[0] / span) * 100;
      var y = ((point[1] - best) / drop) * 26 + 2;
      return x.toFixed(1) + "," + (30 - y).toFixed(1);
    });
    out.line.setAttribute("points", points.join(" "));
    out.curve.hidden = false;
  }

  // The heading is the largest text on the page, and leaving it at what the server rendered
  // when the page loaded means a term that reaches feasibility inside a second sits under the
  // heading for the phase it has already left, contradicting the cell beneath it. The words
  // still come from the server: this picks one of the blocks it rendered and copies it in.
  // Quoting one of them here would be the same drift a comment instead of a variable — and a
  // test asserts none of them appears in this file.
  function say(phase) {
    if (phase === showing) return;
    showing = phase;
    var said = out.phrasing.querySelector('[data-phase="' + phase + '"]');
    if (!said) return;
    out.headline.textContent = said.querySelector("b").textContent;
    out.explanation.textContent = said.querySelector("span").textContent;
  }

  function show(status) {
    say(status.phase);
    out.phase.textContent = status.phase;
    out.elapsed.textContent = status.elapsed_seconds.toFixed(1) + "s";
    out.penalty.textContent = number(status.penalty);
    out.bound.textContent = number(status.lower_bound);
    out.solutions.textContent = String(status.solutions_found);

    var rules = Object.keys(status.penalty_breakdown);
    out.breakdown.innerHTML = "";
    if (rules.length) {
      var head = out.breakdown.insertRow();
      head.insertCell().outerHTML = "<th>Rule</th>";
      head.insertCell().outerHTML = "<th>Cost</th>";
      rules.forEach(function (rule) {
        var row = out.breakdown.insertRow();
        row.insertCell().textContent = words(rule);
        row.insertCell().textContent = String(status.penalty_breakdown[rule]);
      });
    }
    out.breakdown.hidden = rules.length === 0;

    if (status.penalty !== null && status.penalty !== undefined) {
      seen.push([status.elapsed_seconds, status.penalty]);
      draw();
    }
  }

  stream.addEventListener("status", function (event) {
    show(JSON.parse(event.data));
  });

  // The server owns the sentences a settled solve gets — which ending it was, and whether the
  // budget or the arithmetic stopped it. Reloading is how they arrive, rather than a second
  // copy of that prose living here and drifting from `console.solving.wording`.
  stream.addEventListener("done", function (event) {
    show(JSON.parse(event.data));
    stream.close();
    window.location.reload();
  });

  // Without this the browser reconnects three seconds after the server closes the stream, for
  // ever, four times a second — and an open stream holds one of the six connections a browser
  // will make to an origin over HTTP/1.1, so they accumulate across navigations in one tab.
  window.addEventListener("pagehide", function () {
    stream.close();
  });
})();
