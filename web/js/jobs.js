// Live job card: progress, state, pause/stop, login hand-off and log.
import { h, mount, icon, button, fa, num, pct, pill, progressBar, ring, logView, on, post, get, toast } from "./core.js";

export const STATE_LABEL = {
  queued: ["در صف", ""], running: ["در حال اجرا", "blue"], paused: ["متوقف موقت", "orange"],
  waiting: ["منتظر شما", "orange"], done: ["تمام شد", "green"], failed: ["ناموفق", "red"], stopped: ["متوقف شد", ""],
};

export function jobCard(initial, { onDone, onItem, compact = false } = {}) {
  let job = initial;
  const root = h("div", { class: "job-card" });
  const logEl = logView(initial.logs || []);
  const head = h("div", { class: "job-head" });
  const banner = h("div");
  const bar = h("div", { style: { marginTop: "14px" } });
  root.append(head, bar, banner, compact ? h("div") : logEl);

  const render = () => {
    const [label, color] = STATE_LABEL[job.state] || [job.state, ""];
    const finished = ["done", "failed", "stopped"].includes(job.state);
    const p = pct(job.done, job.total);
    mount(head,
      ring(finished && job.state === "done" ? 100 : p),
      h("div", { class: "info" },
        h("div", { class: "row" }, h("b", {}, fa(job.title)), pill(label, color, !finished)),
        h("div", { class: "muted num", style: { fontSize: "13px", marginTop: "2px" } },
          job.total ? `${num(job.done)} از ${num(job.total)}` : "", job.message ? " · " : "", h("span", { class: "ltr" }, job.message || ""))),
      !finished && job.state !== "waiting" ? (job.state === "paused"
        ? button("ادامه", { icon: "play", kind: "tinted", onClick: () => post(`/api/jobs/${job.id}/resume`) })
        : button("توقف موقت", { icon: "pause", onClick: () => post(`/api/jobs/${job.id}/pause`) })) : null,
      !finished ? button("پایان", { icon: "stop", kind: "danger", onClick: () => post(`/api/jobs/${job.id}/stop`) }) : null,
    );
    mount(bar, finished ? null : progressBar(job.done, job.total, { indeterminate: !job.total }));
    if (job.action && job.action.type === "login") {
      mount(banner, h("div", { class: "banner" },
        h("div", { class: "b-ico" }, icon("key", 18, 2)),
        h("div", { class: "txt" }, h("b", {}, "ورود به پنل لازم است"),
          h("small", {}, "در پنجره کروم که باز شده وارد حساب خود شوید. برنامه ورود را خودکار تشخیص می‌دهد؛ یا پس از ورود این دکمه را بزنید.")),
        button("ورود انجام شد", { kind: "primary", icon: "check", onClick: () => post(`/api/jobs/${job.id}/confirm-login`) })));
    } else if (job.state === "failed") {
      mount(banner, h("div", { class: "banner red" }, h("div", { class: "b-ico" }, icon("warn", 18, 2)),
        h("div", { class: "txt" }, h("b", {}, "عملیات با خطا متوقف شد"), h("small", {}, job.error))));
    } else mount(banner);
  };
  render();

  const offs = [
    on("job", (j) => {
      if (j.id !== job.id || (j.version ?? 0) < (job.version ?? 0)) return;
      const was = job.state;
      job = { ...job, ...j };
      render();
      if (["done", "failed", "stopped"].includes(j.state) && !["done", "failed", "stopped"].includes(was)) onDone && onDone(job);
    }),
    on("log", (e) => { if (e.job === job.id) logEl.add(e); }),
    on("item", (e) => { if (e.job === job.id && onItem) onItem(e); }),
  ];
  // catch up in case the job finished before we subscribed
  get(`/api/jobs/${job.id}`).then((j) => {
    if (!logEl.childElementCount) (j.logs || []).forEach((e) => logEl.add(e));
    if ((j.version ?? 0) > (job.version ?? 0)) {
      const was = job.state;
      job = { ...job, ...j };
      render();
      if (["done", "failed", "stopped"].includes(j.state) && !["done", "failed", "stopped"].includes(was)) onDone && onDone(job);
    }
  }).catch(() => {});
  root.destroy = () => offs.forEach((f) => f());
  return root;
}

export const isFinished = (job) => ["done", "failed", "stopped"].includes(job?.state);
