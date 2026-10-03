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
 * A section (a module) can have a video: a take of the app doing what its
 * lessons teach, recorded by mycelium-promo/learn/record.mjs into learn/video/.
 * It opens the section's first lesson, and is a click away on the course page
 * and on the section's other lessons.
 *
 * Progress is which lessons you marked done, kept in this browser only. A
 * page that can't reach localStorage still works; it just forgets.
 */
(function () {
  "use strict";

  var COURSES = window.MYCELIUM_COURSES || [];
  var KEY = "mycelium.learn.done";
  var root = document.getElementById("learn");


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
  // A course's thumbnail: a screenshot of the app doing what the course
  // teaches, its number, and its track.
  function tile(course, i) {
    var n = (i + 1 < 10 ? "0" : "") + (i + 1);
    return (
      '<div class="thumb">' +
      (course.thumb ? '<img src="' + esc(course.thumb) + '" alt="" loading="lazy">' : "") +
      '<span class="num">' + n + "</span>" +
      '<span class="track">' + esc(course.track || "Course") + "</span></div>"
    );
  }
  function stateFoot(course) {
    var p = progressOf(course);
    if (p.total && p.done === p.total) return '<span class="finished-tag"><i data-lucide="badge-check"></i>Finished</span>';
    if (p.done) return bar(p.pct) + '<span class="cta">Continue <i data-lucide="arrow-right"></i></span>';
    return '<span class="cta">Start <i data-lucide="arrow-right"></i></span>';
  }
  function metaLine(course) {
    var p = progressOf(course);
    return (
      '<div class="meta"><span>' + count(p.total, "lesson", "lessons") + '</span><span class="dot">·</span><span>' +
      minutesOf(course) + " min</span>" +
      (videosOf(course)
        ? '<span class="dot">·</span><span>' + count(videosOf(course), "video", "videos") + "</span>"
        : "") +
      "</div>"
    );
  }
  function bar(pct) {
    return '<div class="bar"><span style="width:' + pct + '%"></span></div>';
  }
  function check(on) {
    return '<span class="check' + (on ? " on" : "") + '">' + (on ? '<i data-lucide="check"></i>' : "") + "</span>";
  }
  function count(n, one, many) { return n + " " + (n === 1 ? one : many); }

  // ── videos ─────────────────────────────────────────────────────────────────

  function clock(seconds) {
    var s = Math.round(seconds || 0);
    return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
  }
  function videosOf(course) {
    return (course.modules || []).filter(function (m) { return m.video; }).length;
  }
  // The player itself. preload="none" so a page of sections costs a poster each.
  function player(video) {
    var base = "learn/video/" + esc(video.take);
    return (
      '<figure class="clip"><video controls playsinline muted preload="none" poster="' + base + '.jpg">' +
      '<source src="' + base + '.mp4" type="video/mp4"></video>' +
      (video.about ? "<figcaption>" + esc(video.about) + "</figcaption>" : "") + "</figure>"
    );
  }
  // A section's video behind a disclosure: the course page and a section's
  // later lessons, where it's there if wanted rather than in the way.
  function folded(video, label) {
    return (
      '<details class="clip-fold"><summary><i data-lucide="play"></i><span>' + esc(label) + "</span>" +
      (video.seconds ? '<span class="mins">' + clock(video.seconds) + "</span>" : "") + "</summary>" +
      player(video) + "</details>"
    );
  }

  // ── views ──────────────────────────────────────────────────────────────────

  function catalog() {
    var first = COURSES[0];
    var lessons = COURSES.reduce(function (n, c) { return n + lessonsOf(c).length; }, 0);
    var minutes = COURSES.reduce(function (n, c) { return n + minutesOf(c); }, 0);
    var hero =
      '<section class="hero"><div class="veil"><div class="label">Mycelium · Learn</div>' +
      "<h1>Scale up your work <em>with agents</em></h1>" +
      '<p class="lede">Courses on the setups that let a few agents carry real work for hours: who does what, ' +
      "how they hold each other to it, and where you come in. Written from using Mycelium on real work.</p>" +
      '<div class="actions">' +
      (first ? '<a class="btn" href="#/c/' + esc(first.id) + '">Start with the core workflow <i data-lucide="arrow-right"></i></a>' : "") +
      '<a class="btn ghost" href="walkthrough.html">New to Mycelium? Your first room</a></div>' +
      '<div class="stats"><span><b>' + COURSES.length + "</b>courses</span><span><b>" + lessons +
      "</b>lessons</span><span><b>" + minutes + "</b>minutes in all</span></div></div>" +
      '<div class="stage" aria-hidden="true">' +
      '<div class="shot back"><img src="app-board-columns.png" alt=""></div>' +
      '<div class="shot front"><img src="walk-thread.png" alt=""></div></div></section>';

    // The core course opens the catalog and the capstone closes it, each as a
    // wide card; the courses between them sit in a row.
    function wide(c, i, mirrored) {
      return (
        '<a class="featured glass' + (mirrored ? " mirrored" : "") + '" href="#/c/' + esc(c.id) + '">' + tile(c, i) +
        '<div class="body"><div class="label">' + esc(c.track || "Course") + "</div><h3>" + esc(c.title) +
        "</h3><p>" + esc(c.tagline) + "</p>" + metaLine(c) + '<div class="foot">' + stateFoot(c) +
        "</div></div></a>"
      );
    }
    var last = COURSES.length > 2 && COURSES[COURSES.length - 1].track === "Capstone" ? COURSES[COURSES.length - 1] : null;
    var featured = first ? wide(first, 0, false) : "";
    var capstone = last ? wide(last, COURSES.length - 1, true) : "";
    var middle = COURSES.slice(1, last ? -1 : undefined);
    var rest = middle.map(function (c, i) {
      return (
        '<a class="card glass" href="#/c/' + esc(c.id) + '">' + tile(c, i + 1) +
        '<div class="body"><h3>' + esc(c.title) + "</h3><p>" + esc(c.tagline) + "</p>" + metaLine(c) +
        '<div class="foot">' + stateFoot(c) + "</div></div></a>"
      );
    }).join("");
    return (
      hero +
      '<div class="section-head"><h2>Courses</h2><span class="label">' + COURSES.length + " to start</span></div>" +
      featured + '<div class="grid">' + rest + "</div>" + capstone
    );
  }

  function ticks(items, cls, icon) {
    return (
      '<ul class="ticks ' + (cls || "") + '">' +
      (items || []).map(function (o) {
        return '<li><i data-lucide="' + (icon || "check") + '"></i><span>' + esc(o) + "</span></li>";
      }).join("") +
      "</ul>"
    );
  }

  function coursePage(course) {
    var i = COURSES.indexOf(course);
    var p = progressOf(course);
    var next = nextLesson(course);
    var modules = (course.modules || []).map(function (m) {
      var mins = (m.lessons || []).reduce(function (n, l) { return n + (l.minutes || 0); }, 0);
      var rows = (m.lessons || []).map(function (l) {
        return (
          '<a class="row" href="#/c/' + esc(course.id) + "/" + esc(l.id) + '">' +
          check(isDone(course, l.id)) + "<span>" + esc(l.title) + "</span>" +
          (l.quiz ? '<span class="tag" title="Has a quick check">Check</span>' : "") +
          '<span class="mins">' + (l.minutes || 0) + " min</span></a>"
        );
      }).join("");
      return (
        '<div class="module"><div class="module-head"><span>' + esc(m.title) + '</span><span class="muted">' +
        count((m.lessons || []).length, "lesson", "lessons") + " · " + mins + " min</span></div>" +
        (m.video ? folded(m.video, "Watch this section") : "") + rows + "</div>"
      );
    }).join("");
    var finished = p.total && p.done === p.total;
    var action = next
      ? '<a class="btn" href="#/c/' + esc(course.id) + "/" + esc(next.id) + '">' +
        (finished ? "Go through it again" : p.done ? "Continue where you left off" : "Start the course") +
        ' <i data-lucide="arrow-right"></i></a>'
      : "";
    return (
      '<div class="crumbs"><a href="#/">Learn</a> › ' + esc(course.title) + "</div>" +
      (finished
        ? '<div class="finished glass"><i data-lucide="badge-check"></i><div><h3>You finished this course</h3>' +
          "<p>Every lesson is marked done. Run the exercise on real work if you haven't yet.</p></div></div>"
        : "") +
      '<div class="course-hero"><div class="veil"><div class="label">' + esc(course.track || "Course") + " · Course " + (i + 1) +
      "</div><h1>" + esc(course.title) + '</h1><p class="lede">' + esc(course.tagline) + "</p>" + metaLine(course) +
      (course.takeaway
        ? '<div class="take" style="margin-top:18px"><i data-lucide="sparkles"></i><p><strong>You\'ll come away with:</strong> ' +
          esc(course.takeaway) + "</p></div>"
        : "") +
      "</div>" +
      '<aside class="side glass">' + tile(course, i) + '<div class="inner">' +
      (p.done ? '<div class="meta">' + bar(p.pct) + "<span>" + p.done + " of " + p.total + " done</span></div>" : "") +
      action + '<a class="btn ghost" href="#/">All courses</a></div></aside></div>' +
      '<div class="course-body"><div>' +
      (course.outcomes ? '<section class="block glass"><h3>What you\'ll be able to do</h3>' + ticks(course.outcomes) + "</section>" : "") +
      '<section class="block glass"><h3>Lessons</h3>' + modules + "</section></div>" +
      (course.needs ? '<section class="block glass"><h3>You\'ll need</h3>' + ticks(course.needs, "one need", "circle-dot") + "</section>" : "<div></div>") +
      "</div>"
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
        '<div class="mod label">' + esc(m.title) + "</div>" +
        (m.lessons || []).map(function (l) {
          return (
            '<a class="row' + (l.id === lesson.id ? " here" : "") + '" href="#/c/' + esc(course.id) + "/" +
            esc(l.id) + '">' + check(isDone(course, l.id)) + "<span>" + esc(l.title) + "</span>" +
            '<span class="mins">' + (l.minutes || 0) + "m</span></a>"
          );
        }).join("")
      );
    }).join("");

    var video = "";
    if (here.module.video) {
      video = here.indexInModule === 0 ? player(here.module.video) : folded(here.module.video, "Watch this section again");
    }

    var quiz = "";
    if (lesson.quiz) {
      quiz =
        '<div class="quiz" id="quiz"><div class="label">Quick check</div><p class="q">' + esc(lesson.quiz.question) + "</p>" +
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
      '<div class="lesson"><nav class="lesson-nav glass" aria-label="Lessons">' +
      '<div class="course-title"><a href="#/c/' + esc(course.id) + '">' + esc(course.title) + "</a></div>" +
      '<div class="progress">' + bar(p.pct) + "<span>" + p.done + " of " + p.total + " done</span></div>" + nav + "</nav>" +
      '<article class="lesson-main glass"><div class="label">' + esc(here.module.title) + " · Lesson " + (at + 1) +
      " of " + all.length + "</div><h1>" + esc(lesson.title) + '</h1><div class="mins-line">About ' + (lesson.minutes || 0) +
      ' minutes</div><div class="lesson-body">' + video + (lesson.html || "") + "</div>" + quiz + foot + "</article></div>"
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
