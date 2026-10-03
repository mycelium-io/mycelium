// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/*
 * Learn: a course catalog, a course page and a lesson view, over the courses
 * generate_docs.py compiles into learn-data.js (window.MYCELIUM_COURSES).
 *
 *   #/                     the catalog
 *   #/c/<course>           a course: what you'll learn, its lessons
 *   #/c/<course>/<lesson>  a lesson, with the course's lessons beside it
 *
 * Progress is which lessons you marked done, kept in this browser only. A
 * page that can't reach localStorage still works; it just forgets.
 */
(function () {
  "use strict";

  var COURSES = window.MYCELIUM_COURSES || [];
  var KEY = "mycelium.learn.done";
  var root = document.getElementById("learn");

  // Each course's tile, in the site's own colors.
  var TILES = [
    "linear-gradient(135deg, var(--accent), var(--accent2))",
    "linear-gradient(135deg, var(--accent2), var(--code-kw))",
    "linear-gradient(135deg, var(--green), var(--accent))",
    "linear-gradient(135deg, var(--code-flag), var(--accent2))",
  ];

  // ── progress ───────────────────────────────────────────────────────────────

  function loadDone() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function saveDone(done) {
    try { localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) { /* forgets */ }
  }
  function isDone(course, lessonId) {
    var list = loadDone()[course.id] || [];
    return list.indexOf(lessonId) !== -1;
  }
  function markDone(course, lessonId) {
    var done = loadDone();
    var list = done[course.id] || [];
    if (list.indexOf(lessonId) === -1) list.push(lessonId);
    done[course.id] = list;
    saveDone(done);
  }

  // ── course shape ───────────────────────────────────────────────────────────

  function lessonsOf(course) {
    var out = [];
    (course.modules || []).forEach(function (m, mi) {
      (m.lessons || []).forEach(function (l, li) {
        out.push({ lesson: l, module: m, moduleIndex: mi, indexInModule: li });
      });
    });
    return out;
  }
  function minutesOf(course) {
    return lessonsOf(course).reduce(function (n, x) { return n + (x.lesson.minutes || 0); }, 0);
  }
  function progressOf(course) {
    var all = lessonsOf(course);
    var n = all.filter(function (x) { return isDone(course, x.lesson.id); }).length;
    return { done: n, total: all.length, pct: all.length ? Math.round((100 * n) / all.length) : 0 };
  }
  function nextLesson(course) {
    var all = lessonsOf(course);
    for (var i = 0; i < all.length; i++) if (!isDone(course, all[i].lesson.id)) return all[i].lesson;
    return all.length ? all[0].lesson : null;
  }
  function find(id) {
    for (var i = 0; i < COURSES.length; i++) if (COURSES[i].id === id) return COURSES[i];
    return null;
  }

  // ── bits ───────────────────────────────────────────────────────────────────

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function tile(course, i) {
    return (
      '<div class="thumb" style="background:' + TILES[i % TILES.length] + '">' +
      '<span class="glyph">' + esc(course.title.charAt(0)) + "</span>" +
      '<span class="level">' + esc(course.level || "Course") + "</span></div>"
    );
  }
  function bar(pct) {
    return '<div class="bar"><span style="width:' + pct + '%"></span></div>';
  }
  function check(on) {
    return '<span class="check' + (on ? " on" : "") + '">' + (on ? '<i data-lucide="check"></i>' : "") + "</span>";
  }
  function count(n, one, many) { return n + " " + (n === 1 ? one : many); }

  // ── views ──────────────────────────────────────────────────────────────────

  function catalog() {
    var cards = COURSES.map(function (c, i) {
      var p = progressOf(c);
      var foot = p.done === p.total && p.total
        ? '<span class="done-badge">Finished</span>'
        : p.done
          ? bar(p.pct) + '<span class="cta">Continue</span>'
          : '<span class="cta">Start</span>';
      return (
        '<a class="card learn-panel" href="#/c/' + esc(c.id) + '">' + tile(c, i) +
        '<div class="card-body"><h3>' + esc(c.title) + "</h3><p>" + esc(c.tagline) + "</p>" +
        '<div class="meta"><span>' + count(p.total, "lesson", "lessons") + "</span><span>·</span><span>" +
        minutesOf(c) + " min</span></div>" +
        '<div class="card-foot">' + foot + "</div></div></a>"
      );
    }).join("");
    return (
      '<section class="hero learn-panel"><div class="eyebrow">Learn</div>' +
      "<h1>Learn to work with agents</h1>" +
      "<p>Short courses on the setups that hold up in real work. A few lessons each, a few minutes a lesson, " +
      "with something to try at the end.</p>" +
      '<p class="start">New to Mycelium? Start with <a href="walkthrough.html">Your First Room</a>.</p></section>' +
      '<div class="grid">' + cards + "</div>"
    );
  }

  function coursePage(course) {
    var i = COURSES.indexOf(course);
    var p = progressOf(course);
    var next = nextLesson(course);
    var outcomes = (course.outcomes || []).map(function (o) {
      return '<li><i data-lucide="check"></i><span>' + esc(o) + "</span></li>";
    }).join("");
    var modules = (course.modules || []).map(function (m) {
      var mins = (m.lessons || []).reduce(function (n, l) { return n + (l.minutes || 0); }, 0);
      var rows = (m.lessons || []).map(function (l) {
        return (
          '<a class="lesson-row" href="#/c/' + esc(course.id) + "/" + esc(l.id) + '">' +
          check(isDone(course, l.id)) + "<span>" + esc(l.title) + "</span>" +
          (l.quiz ? '<span class="muted" title="Has a quick check">· quiz</span>' : "") +
          '<span class="mins">' + (l.minutes || 0) + " min</span></a>"
        );
      }).join("");
      return (
        '<div class="module"><div class="module-head"><span>' + esc(m.title) + '</span><span class="muted">' +
        count((m.lessons || []).length, "lesson", "lessons") + " · " + mins + " min</span></div>" + rows + "</div>"
      );
    }).join("");
    var finished = p.total && p.done === p.total;
    var action = next
      ? '<a class="btn" href="#/c/' + esc(course.id) + "/" + esc(next.id) + '">' +
        (finished ? "Go through it again" : p.done ? "Continue" : "Start the course") +
        ' <i data-lucide="arrow-right"></i></a>'
      : "";
    return (
      '<div class="crumbs"><a href="#/">Learn</a> › ' + esc(course.title) + "</div>" +
      (finished
        ? '<div class="finished learn-panel"><i data-lucide="badge-check"></i><div><h3>You finished this course</h3>' +
          "<p>Every lesson is marked done. Try the exercise on real work if you haven't yet.</p></div></div>"
        : "") +
      '<div class="course"><div class="course-main learn-panel">' +
      '<div class="eyebrow">' + esc(course.level || "Course") + "</div><h1>" + esc(course.title) + "</h1>" +
      '<p class="tagline">' + esc(course.tagline) + "</p>" +
      (outcomes ? '<div class="outcomes"><h3>What you\'ll learn</h3><ul>' + outcomes + "</ul></div>" : "") +
      "<h3>Lessons</h3>" + modules + "</div>" +
      '<aside class="side-card learn-panel">' + tile(course, i) + '<div class="side-body">' +
      '<div class="meta"><span>' + count(p.total, "lesson", "lessons") + "</span><span>·</span><span>" +
      minutesOf(course) + " min</span></div>" +
      (p.done ? '<div class="meta">' + bar(p.pct) + "<span>" + p.done + " of " + p.total + "</span></div>" : "") +
      action + '<a class="btn ghost" href="#/">All courses</a></div></aside></div>'
    );
  }

  function lessonPage(course, lessonId) {
    var all = lessonsOf(course);
    var at = -1;
    for (var k = 0; k < all.length; k++) if (all[k].lesson.id === lessonId) at = k;
    if (at === -1) return coursePage(course);
    var here = all[at];
    var lesson = here.lesson;
    var prev = all[at - 1];
    var next = all[at + 1];
    var p = progressOf(course);

    var nav = (course.modules || []).map(function (m) {
      return (
        '<div class="mod">' + esc(m.title) + "</div>" +
        (m.lessons || []).map(function (l) {
          return (
            '<a class="lesson-row' + (l.id === lesson.id ? " here" : "") + '" href="#/c/' + esc(course.id) + "/" +
            esc(l.id) + '">' + check(isDone(course, l.id)) + "<span>" + esc(l.title) + "</span>" +
            '<span class="mins">' + (l.minutes || 0) + "m</span></a>"
          );
        }).join("")
      );
    }).join("");

    var quiz = "";
    if (lesson.quiz) {
      quiz =
        '<div class="quiz" id="quiz"><div class="eyebrow">Quick check</div><p class="q">' + esc(lesson.quiz.question) + "</p>" +
        lesson.quiz.options.map(function (o, i) {
          return '<button class="opt" data-opt="' + i + '">' + esc(o) + "</button>";
        }).join("") +
        '<p class="why" id="quiz-why" hidden></p></div>';
    }

    var foot =
      '<div class="lesson-foot">' +
      (prev
        ? '<a class="btn ghost" href="#/c/' + esc(course.id) + "/" + esc(prev.lesson.id) + '"><i data-lucide="arrow-left"></i>Previous</a>'
        : '<a class="btn ghost" href="#/c/' + esc(course.id) + '">Course overview</a>') +
      '<button class="btn" id="complete">' +
      (next ? 'Mark done and continue <i data-lucide="arrow-right"></i>' : 'Finish the course <i data-lucide="check"></i>') +
      "</button></div>";

    return (
      '<div class="crumbs"><a href="#/">Learn</a> › <a href="#/c/' + esc(course.id) + '">' + esc(course.title) +
      "</a> › " + esc(lesson.title) + "</div>" +
      '<div class="lesson"><nav class="lesson-nav learn-panel" aria-label="Lessons">' +
      '<div class="course-title"><a href="#/c/' + esc(course.id) + '">' + esc(course.title) + "</a></div>" +
      '<div class="progress">' + bar(p.pct) + "<span>" + p.done + " of " + p.total + " done</span></div>" + nav + "</nav>" +
      '<article class="lesson-main learn-panel"><div class="eyebrow">' + esc(here.module.title) + " · Lesson " + (at + 1) +
      " of " + all.length + "</div><h1>" + esc(lesson.title) + '</h1><div class="mins-line">About ' + (lesson.minutes || 0) +
      ' minutes</div><div class="lesson-body">' + (lesson.html || "") + "</div>" + quiz + foot + "</article></div>"
    );
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  function route() {
    var parts = (location.hash || "#/").replace(/^#\/?/, "").split("/").filter(Boolean);
    var course = parts[0] === "c" ? find(parts[1]) : null;
    var lessonId = course && parts[2];
    if (course && lessonId) root.innerHTML = lessonPage(course, lessonId);
    else if (course) root.innerHTML = coursePage(course);
    else root.innerHTML = catalog();
    document.title = (course ? course.title + " · " : "") + "Learn · mycelium";
    if (window.lucide) window.lucide.createIcons();
    wire(course, lessonId);
    window.scrollTo(0, 0);
  }

  function wire(course, lessonId) {
    if (!course || !lessonId) return;
    var all = lessonsOf(course);
    var at = all.map(function (x) { return x.lesson.id; }).indexOf(lessonId);
    var lesson = at === -1 ? null : all[at].lesson;
    var complete = document.getElementById("complete");
    if (complete) {
      complete.addEventListener("click", function () {
        markDone(course, lessonId);
        var next = all[at + 1];
        location.hash = next ? "#/c/" + course.id + "/" + next.lesson.id : "#/c/" + course.id;
      });
    }
    var quiz = document.getElementById("quiz");
    if (quiz && lesson && lesson.quiz) {
      quiz.addEventListener("click", function (e) {
        var btn = e.target.closest("button.opt");
        if (!btn) return;
        var pick = Number(btn.getAttribute("data-opt"));
        var right = lesson.quiz.answer;
        quiz.querySelectorAll("button.opt").forEach(function (b, i) {
          b.classList.toggle("right", i === right);
          b.classList.toggle("wrong", i === pick && pick !== right);
        });
        var why = document.getElementById("quiz-why");
        why.textContent = (pick === right ? "Right. " : "Not quite. ") + (lesson.quiz.why || "");
        why.hidden = false;
      });
    }
  }

  window.addEventListener("hashchange", route);
  route();
})();
