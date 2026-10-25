"""The overnight controller: run planned work, monitor it and preserve checkpoints.

The stateful Controller stays together; plans, process ownership and persistence
are supplied by the neighboring harness modules."""
import overnight_common as common
import overnight_plan as plan
import overnight_processes as processes


# ============================================================ the controller

class Controller:
    """overnight.py run: the items in plan order, one at a time (section 5.1)."""

    def __init__(self, out, args):
        self.out = common.Path(out)
        self.args = args
        self.plan = common.json.loads((self.out / "plan.resolved.json").read_text(encoding="utf-8"))
        self.items = {item["id"]: item for item in self.plan["items"]}
        self.smoke = self.plan["smoke"]
        self.fake = bool(getattr(args, "fake", False) or self.plan.get("fake"))
        self.state = common.load_state(self.out)
        self.session = self.state["sessions"][-1]
        self.job = None
        self.monitor = None
        self.server = None          # (proc, job) of the test server
        self.last = {"soak": None, "drift": None, "poll": None, "pids": 0.0}
        self.d_started = None
        self.t0 = common.time.monotonic()
        self.active_base = self.session.get("active_s", 0.0)
        self.paused_base = self.session.get("paused_s", 0.0)
        self.paused_since = None
        self.probe_proc = None
        periods = common.SMOKE_PERIODS if self.smoke else {
            "soak": common.SOAK_PROBE_S, "drift": common.DRIFT_PROBE_S, "poll": common.POOL_POLL_S}
        self.periods = periods

    # ---------------------------------------------------------------- bookkeeping

    def save(self):
        now = common.time.monotonic()
        paused = self.paused_base + (now - self.paused_since if self.paused_since else 0.0)
        self.session["paused_s"] = round(paused, 1)
        self.session["active_s"] = round(self.active_base + (now - self.t0) - (paused - self.paused_base), 1)
        common.save_state(self.out, self.state)

    def item_state(self, item_id):
        return self.state["items"].setdefault(item_id, {"status": "pending", "attempts": 0})

    def ctx(self):
        return {"OUT": str(self.out).replace("\\", "/"), "MAIN": self.plan["main"], "smoke": self.smoke,
                "matchups": 1 if self.smoke else 4, "idle_s": 30 if self.smoke else 120,
                "card_data_mtime": self.state["identity"].get("card_data_mtime") or 0}

    def env(self, item=None):
        env = dict(common.os.environ)
        env.pop("DECKLAB_STOP_FILE", None)
        if self.smoke:
            extra = self.out / "smoke-config.json"
            extra.write_text(common.json.dumps({"forge_workers": common.SMOKE_WORKERS}), encoding="utf-8")
            env["DECKLAB_CONFIG_EXTRA"] = str(extra)
        for k, v in (item or {}).get("env", {}).items():
            env[k] = str(v)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def remaining(self):
        """min(budget - active, deadline - now), in seconds."""
        self.save()
        return min(self.session["budget_s"] - self.session["active_s"], self.session["deadline_epoch"] - common.time.time())

    def filler_owed(self):
        return plan.soak_owed(self.plan["soak_min_s"], self.session.get("soak_s", 0.0),
                         self.session.get("soak_server_s", 0.0))

    def record_pids(self):
        if self.job is None:
            return
        own = {tuple(x) for x in self.state.get("own_pids", [])}
        for pid in self.job.pids():
            if pid != common.os.getpid():
                created = processes.creation_time(pid)
                if created:
                    own.add((pid, created))
        self.state["own_pids"] = sorted(list(x) for x in own)
        self.last["pids"] = common.time.monotonic()

    # ---------------------------------------------------------------- the run

    def run(self):
        lock = processes.Lock(self.out)
        if not lock.acquire():
            common.log(self.out, "Another controller is running this run (its .lock is held).")
            return common.EXIT_REFUSED
        try:
            return self._run()
        finally:
            if self.monitor:
                self.monitor.stop()
            lock.release()

    def _run(self):
        common.sys.path.insert(0, str(common.HERE))
        import overnight_monitor
        processes.keep_awake()
        self.job = processes.Job()
        if not self.job.assign_self() and common.sys.platform == "win32":
            common.log(self.out, "WARNING: the controller couldn't join the run's job, so the monitor can't tell the run's "
                          "processes from others (the idle rules may pause the run on its own load).")
        self.monitor = overnight_monitor.Monitor(self.out / "cpu.csv", job=self.job,
                                                 until=self.session["deadline_epoch"] + 1800)
        self.monitor.start()
        common.log(self.out, f"Session {len(self.state['sessions'])} started (pid {common.os.getpid()})"
                      + (" for the end only (D9, E4, E5)." if getattr(self.args, "end_only", False) else "."))
        self._clean_interrupted()
        if getattr(self.args, "end_only", False):
            return self._end_only()
        order = [item["id"] for item in self.plan["items"]]
        if self.session.get("needs_upfront", True):
            self._upfront()
        code = common.EXIT_STOPPED
        requeue = []
        i = 0
        while i < len(order):
            item_id = order[i]
            item = self.items[item_id]
            st = self.item_state(item_id)
            nxt = self.items[order[i + 1]] if i + 1 < len(order) else None
            if st["status"] in ("done", "skipped", "dropped", "cut", "noisy") or item["status"] != "pending":
                if item["status"] != "pending" and st["status"] == "pending":
                    st.update(status=item["status"], note=item.get("why"),
                              **({"not_built": item["not_built"]} if item.get("not_built") else {}))
                    self.save()
                i += 1
                code = self._block_end(item, nxt, requeue)
                if code is not None:
                    break
                continue
            if st["status"] == "failed" and st.get("attempts", 0) >= 2:
                i += 1
                continue
            if self._failfast() and item["block"] == "D" and self.state.get("diagnostics") is None:
                self._diagnostics()
            if self._failfast() and (item["block"] == "D" and item.get("internal") not in ("server-start",
                                                                                           "server-stop")):
                st.update(status="skipped", note="fail-fast: an engine check failed (MG2-MG5)")
                self.save()
                i += 1
                continue
            if self._owner_stop():
                common.log(self.out, "The owner's STOP file: stopping (the test server is stopped, then cleanup and "
                              "the report).")
                code = common.EXIT_OWNER_STOP
                break
            if common.time.time() >= self.session["deadline_epoch"]:
                common.log(self.out, "The deadline passed: stopping.")
                code = common.EXIT_DEADLINE
                break
            if item["priority"] > 0:
                left = self.remaining() - plan.reserve(item["priority"], self._pending(), self.filler_owed(),
                                                  self.plan["end_reserve_s"])
                decision, value = plan.fit(item, left)
                if decision == "dropped":
                    st.update(status="dropped", note=value)
                    self.state.setdefault("dropped", []).append({"id": item_id, "why": value})
                    common.log(self.out, f"{item_id} dropped: {value}")
                    self.save()
                    i += 1
                    continue
                item["scale"] = value
            self._check_monitor()
            self._wait_until_free(item)
            if item["block"] == "D" and not item.get("exclusive") and not item.get("internal") and self._drift_due():
                self._drift_probe()
            if self.smoke and item.get("internal") == "server-start" and "stop_drill" not in self.state["drill"]:
                self._drill_stop()
            outcome = self._do(item)
            if outcome.get("preempted"):
                if outcome["preempted"] == "drift":
                    self._drift_probe()
                continue                    # the same item again: it plays only what's missing
            if item["block"] == "C" and outcome.get("status") in ("done", "failed"):
                self._c_gate(item)
            if outcome.get("status") == "noisy" and not outcome.get("note", "").endswith("twice"):
                requeue.append(item_id)
            if outcome.get("exit") is not None:
                code = outcome["exit"]
                break
            if item_id == "A1" and self.item_state("A1").get("mg1_failed"):
                code = common.EXIT_FAILFAST
                break
            i += 1
            code = self._block_end(item, nxt, requeue)
            if code is not None:
                break
        else:
            code = common.EXIT_STOPPED
        if code is None:
            code = common.EXIT_STOPPED
        if code in (common.EXIT_FAILFAST, common.EXIT_DEADLINE, common.EXIT_NEVER_IDLE, common.EXIT_OWNER_STOP):
            for item_id in ("D9", "E4", "E5"):         # stop the test server, clean up, report
                if item_id in self.items and self.item_state(item_id).get("status") != "done":
                    self._do(self.items[item_id])
        self.session["ended"] = common.time.strftime("%Y-%m-%dT%H:%M:%S")
        self.session["exit"] = code
        self.save()
        self._report_again()
        return code

    def _end_only(self):
        """run --end-only (the supervisor, after the controller's last allowed crash): stop the test
        server, clean up and report (D9, E4, E5), so E4's cleanup and its 8642 restart run as E4."""
        for item_id in ("D9", "E4", "E5"):
            if item_id in self.items and self.item_state(item_id).get("status") != "done":
                self._do(self.items[item_id])
        self.session["ended"] = common.time.strftime("%Y-%m-%dT%H:%M:%S")
        self.session["gave_up"] = True
        self.save()
        self._report_again()
        return common.EXIT_STOPPED

    def _report_again(self):
        """After E5: write the report once more, so it shows E5 done and the session's exit."""
        if self.item_state("E5").get("status") != "done":
            return
        try:
            common.sys.path.insert(0, str(common.HERE))
            import overnight_report
            overnight_report.write(self.out)
        except Exception as e:
            common.log(self.out, f"The report couldn't be written again: {type(e).__name__}: {e}")

    # ---------------------------------------------------------------- fail-fast diagnostics (section 6 C)

    DIAG_MAX_S = 45 * 60
    DIAG = (("c1", ["{L}", "parity", "--out", "{OUT}/C/diag/c1", "--constructed", "{games:100}", "--commander",
                    "{games:5}", "--replay-differences"], 12 * 60),
            ("c2", ["{L}", "cardlog-onoff", "--out", "{OUT}/C/diag/c2", "--games", "{games:400}",
                    "--replay-differences"], 5 * 60),
            ("c3", ["{F}", "serve-check", "--games", "{games:120}"], 9 * 60))

    def _diagnostics(self):
        """Fail-fast (section 6 C): after a failed MG2-MG5, before D is skipped, spend up to 45 min
        (and never E's reserve) on bigger reruns of the checks: C1 at 100 Constructed games, C2 at
        400, serve-check at 120. Each writes under $OUT/C/diag/; nothing goes to staging. The
        experiments are not run: they pair with staging's D1 control, which fail-fast skips."""
        found = {"started": common.time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": {},
                 "failed_gates": [i for i in ("C1", "C2", "C3", "C4") if self.item_state(i).get("gate_failed")],
                 "not_run": "the experiments (they pair with staging's D1 control, which fail-fast skips)"}
        self.state["diagnostics"] = found
        self.save()
        e_left = sum(plan.item_est(i) for i in self._pending() if i["block"] == "E")
        budget = min(self.DIAG_MAX_S, self.remaining() - self.plan["end_reserve_s"] - e_left)
        t0 = common.time.monotonic()
        folder = self.out / "C" / "diag"
        folder.mkdir(parents=True, exist_ok=True)
        for name, cmd, est in self.DIAG:
            left = budget - (common.time.monotonic() - t0)
            if left < 60 or self._owner_stop() or common.time.time() >= self.session["deadline_epoch"]:
                found["runs"][name] = {"status": "dropped", "note": f"{max(0, int(left // 60))} min left"}
                continue
            item = {"id": f"C-diag-{name}", "block": "C", "priority": 0, "exclusive": True, "est_s": est}
            sub = folder / name
            sub.mkdir(parents=True, exist_ok=True)
            started = common.time.monotonic()
            outcome = self._children(item, sub, cmds=[cmd], limit_s=left)
            found["runs"][name] = {"status": outcome.get("status"), "codes": outcome.get("codes"),
                                   "note": outcome.get("note"), "wall_s": round(common.time.monotonic() - started, 1)}
            self.state["items"].pop(item["id"], None)
            self.save()
        found["ended"] = common.time.strftime("%Y-%m-%dT%H:%M:%S")
        common.log(self.out, "Fail-fast diagnostics: " + ", ".join(f"{k} {v['status']}" for k, v in found["runs"].items()))
        self.save()

    def _block_end(self, item, nxt, requeue):
        """At the end of a block: a timing leg that was noisy once runs once more, if there's time."""
        if nxt is not None and nxt["block"] == item["block"] and nxt["id"] != "B1b":
            return None
        while requeue:
            item_id = requeue.pop(0)
            again = self.items[item_id]
            left = self.remaining() - plan.reserve(again["priority"], self._pending(), self.filler_owed(),
                                              self.plan["end_reserve_s"])
            if again["priority"] > 0 and plan.fit(again, left)[0] == "dropped":
                continue
            self.item_state(item_id)["status"] = "pending"
            self._wait_until_free(again)
            outcome = self._do(again)
            if outcome.get("exit") is not None:
                return outcome["exit"]
        return None

    def _drill_stop(self):
        """The drill (--smoke): an item that ignores its STOP file must be ended by TerminateJobObject."""
        folder = self.out / "drill" / "stop"
        folder.mkdir(parents=True, exist_ok=True)
        stop = folder / "STOP"
        env = self.env()
        env["DECKLAB_STOP_FILE"] = str(stop)
        job = processes.Job()
        proc = processes.start_child([common.PY, str(common.LEGS), "ignore-stop", "--seconds", "300"],
                                     str(common.TREE), env, folder / "out.txt", job)
        common.time.sleep(3)
        stop.write_text("drill", encoding="utf-8")
        until = common.time.monotonic() + common.SMOKE_STOP_GRACE_S
        while proc.poll() is None and common.time.monotonic() < until:
            common.time.sleep(0.5)
        ignored = proc.poll() is None
        job.terminate()
        try:
            proc.wait(30)
            ended = True
        except common.subprocess.TimeoutExpired:
            ended = False
        job.close()
        self.state["drill"]["stop_drill"] = {"ignored_stop": ignored, "ended_by_job": ignored and ended,
                                             "pass": ignored and ended}
        common.log(self.out, f"Drill: the item that ignores STOP was {'ended by its job' if ended else 'NOT ended'}.")
        self.save()

    def _pending(self):
        out = []
        for item in self.plan["items"]:
            st = self.state["items"].get(item["id"], {})
            if item["status"] == "pending" and st.get("status", "pending") in ("pending", "running", "failed"):
                out.append(dict(item, status="pending"))
        return out

    def _upfront(self):
        pending = self._pending()
        window = self.remaining()
        filler = plan.upfront(pending, window, soak_min_s=self.plan["soak_min_s"],
                         soak_s=self.session.get("soak_s", 0.0), soak_server_s=self.session.get("soak_server_s", 0.0),
                         end_reserve_s=self.plan["end_reserve_s"])
        for item in pending:
            if item["status"] == "dropped":
                self.item_state(item["id"]).update(status="dropped", note=item["why"])
                self.state.setdefault("dropped", []).append({"id": item["id"], "why": item["why"]})
            self.items[item["id"]]["scale"] = item.get("scale", 1.0)
        self.session["filler_planned_s"] = round(filler)
        self.session["needs_upfront"] = False
        common.log(self.out, f"Up-front decision: {sum(1 for i in pending if i['status'] == 'dropped')} items dropped, "
                      f"filler planned {round(filler / 60)} min.")
        self.save()

    C_GATES = {"C1": "gate_mg2", "C2": "gate_mg3", "C3": "gate_mg4", "C4": "gate_mg5"}

    def _c_gate(self, item):
        """Fail-fast (section 6 C): judge the item's gate now (overnight_report's); a failed MG2-MG5
        skips D's items (the fix would change engine keys) and the run ends FAIL."""
        common.sys.path.insert(0, str(common.HERE))
        import overnight_report
        name = self.C_GATES.get(item["id"])
        if not name:
            return
        self.save()
        try:
            found = getattr(overnight_report, name)(self.out, self.state, self.plan)
        except Exception as e:
            found = {"status": "not checked", "detail": f"{type(e).__name__}: {e}"}
        st = self.item_state(item["id"])
        st["gate"] = {"status": found["status"], "detail": found.get("detail")}
        if item["id"] == "C3" and st.get("status") == "failed" and found["status"] == "pass":
            st.update(status="done", note="serve-check said unsure (exit 1); MG4 passes")    # not unfinished
        if found["status"] == "fail":
            st["gate_failed"] = True
            common.log(self.out, f"{item['id']}: its gate failed ({found.get('detail')}): fail-fast.")
        self.save()

    def _failfast(self):
        return any(self.state["items"].get(i, {}).get("gate_failed") for i in ("C1", "C2", "C3", "C4"))

    def _clean_interrupted(self):
        """A resumed or restarted session: items left "running" or "failed" are cleaned up and run
        again (D items play only what's missing; timing legs start from scratch)."""
        for item_id, st in self.state["items"].items():
            if st.get("status") == "running":
                st["status"] = "pending"
                st["note"] = "interrupted; run again"
                item = self.items.get(item_id)
                if item and item.get("timing"):
                    common.shutil.rmtree(self.out / item["block"] / item_id.lower(), ignore_errors=True)
        if self.item_state("D0").get("status") == "done" and self.item_state("D9").get("status") != "done":
            self.item_state("D0")["status"] = "pending"     # the test server starts again
        found = self._leftovers("resume")
        drill = self.state.get("drill") or {}
        if drill.get("killed") and "after_kill" not in drill:
            drill["after_kill"] = {"leftovers": found, "restarted": common.time.strftime("%H:%M:%S")}
        self.save()

    def _leftovers(self, when):
        """Processes recorded as the run's (own_pids) that are still alive and belong to no live
        item: ended by pid (taskkill /T /F), and listed."""
        found = []
        live = {pid for pid in (self.job.pids() if self.job else [])}
        names = processes._names()
        for pid, created in self.state.get("own_pids", []):
            if pid == common.os.getpid() or pid in live or names.get(pid) == "conhost.exe":
                continue
            if processes.running(pid, created):
                found.append(pid)
                processes.kill_pid(pid)
        if found:
            self.state.setdefault("leftovers", []).append({"when": when, "pids": found,
                                                          "at": common.time.strftime("%H:%M:%S")})
            common.log(self.out, f"Leftovers ended ({when}): {found}")
        return found

    def _owner_stop(self):
        """The owner's graceful stop: a file named STOP in the run's folder (OUT/STOP). The running
        item stops as the page's Stop does, keeping its games; then D9, E4 and E5 run."""
        return (self.out / "STOP").exists()

    def _wait_until_free(self, item):
        """The pause rule (section 5.2): no new item starts while the PC is in use. Not in --smoke."""
        if self.smoke or self.fake or self.monitor is None:
            return
        while self.monitor.in_use() and not self._owner_stop():
            if self.paused_since is None:
                self.paused_since = common.time.monotonic()
                common.log(self.out, "The PC is in use: paused.")
            if common.time.time() >= self.session["deadline_epoch"]:
                return
            while not self.monitor.free_for(300, other_max=5.0):
                common.time.sleep(5)
                if common.time.time() >= self.session["deadline_epoch"] or self._owner_stop():
                    break
        if self.paused_since is not None:
            self.paused_base += common.time.monotonic() - self.paused_since
            self.paused_since = None
            common.log(self.out, "Resumed.")
            self.save()

    # ---------------------------------------------------------------- one item

    def _do(self, item):
        """Run one item; its outcome ({"status", "note", "exit": the controller's exit code or None,
        "preempted"})."""
        st = self.item_state(item["id"])
        st.update(status="running", attempts=st.get("attempts", 0) + 1, session=len(self.state["sessions"]),
                  started=common.time.strftime("%Y-%m-%dT%H:%M:%S"), scale=item.get("scale", 1.0))
        self.save()
        folder = self.out / item["block"] / item["id"].lower()
        folder.mkdir(parents=True, exist_ok=True)
        t = common.time.monotonic()
        handler = getattr(self, "_internal_" + item.get("internal", "").replace("-", "_"), None)
        try:
            if handler is not None and not (self.fake and item.get("internal") not in ("filler",)):
                outcome = handler(item, folder)
            elif handler is not None and self.fake:
                outcome = self._fake_internal(item, folder)
            else:
                outcome = self._children(item, folder)
        except Exception as e:      # the item fails; the run goes on
            import traceback
            common.log(self.out, f"{item['id']} failed with a harness error: {type(e).__name__}: {e}")
            (folder / "harness-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            outcome = {"status": "failed", "note": f"harness error: {type(e).__name__}: {e}"}
        st.update(outcome)
        st["ended"] = common.time.strftime("%Y-%m-%dT%H:%M:%S")
        st["active_s"] = round(st.get("active_s", 0.0) + common.time.monotonic() - t, 1)
        if item["block"] == "D" and item.get("soak") and item.get("internal") != "filler":
            self._add_soak(item, common.time.monotonic() - t, t)
        (folder / "done.json").write_text(common.json.dumps({"id": item["id"], **st}, indent=1), encoding="utf-8")
        common.log(self.out, f"{item['id']}: {st['status']}" + (f" ({st.get('note')})" if st.get("note") else ""))
        if item["block"] in ("B", "C", "D", "E"):
            self._leftovers(item["id"])
        self.record_pids()
        self.save()
        return outcome

    def _add_soak(self, item, seconds, since_mono):
        busy = self.monitor.busy_share(since_mono) if self.monitor else 1.0
        soak = seconds * busy
        self.session["soak_s"] = round(self.session.get("soak_s", 0.0) + soak, 1)
        if item.get("pool") == "server" and (self.fake or processes._http_ok(common.SERVER_PORT)):
            self.session["soak_server_s"] = round(self.session.get("soak_server_s", 0.0) + soak, 1)

    def _children(self, item, folder, cmds=None, limit_s=None):
        """Run an item's commands in turn, each in the item's own job. Returns the item's outcome."""
        cmds = cmds if cmds is not None else item.get("cmds") or []
        if self.smoke and item.get("smoke_cmds") is not None:
            cmds = [cmds[i] for i in item["smoke_cmds"] if i < len(cmds)]
        stop_file = folder / "STOP"
        if stop_file.exists():
            stop_file.unlink()
        est = plan.item_est(item) or 60.0
        started = common.time.monotonic()
        codes, walls, cut, noisy_t0 = [], [], False, common.time.monotonic()
        for n, cmd in enumerate(cmds):
            cmd_t0 = common.time.monotonic()
            argv, cwd = plan.expand(cmd, self.ctx(), item.get("scale", 1.0))
            if self.fake:
                argv, cwd = [common.PY, str(common.LEGS), "fake-item", "--seconds", str(self.plan.get("fake_seconds", 1)),
                             "--out", str(folder)], str(common.TREE)
            env = self.env(item)
            env["DECKLAB_STOP_FILE"] = str(stop_file)
            job = processes.Job()
            with open(folder / "out.txt", "ab") as f:
                f.write(f"\n=== {' '.join(argv)} (in {cwd})\n".encode("utf-8"))
            proc = processes.start_child(argv, cwd, env, folder / "out.txt", job)
            self.state.setdefault("children", {})[item["id"]] = proc.pid
            self.record_pids()
            self.save()
            stopped = None
            drill = (self.smoke and item["block"] == "D" and not item.get("internal")
                     and not (self.state.get("drill") or {}).get("killed"))
            while proc.poll() is None:
                common.time.sleep(1)
                if drill and common.time.monotonic() - started >= (3 if self.fake else 8):
                    # The drill: the controller kills itself during the first D item; the
                    # supervisor must start it again, and the item must finish.
                    self.state["drill"]["killed"] = {"item": item["id"], "child": proc.pid,
                                                     "at": common.time.strftime("%H:%M:%S")}
                    self.record_pids()
                    self.save()
                    common.log(self.out, f"Drill: the controller kills itself during {item['id']}.")
                    common.os._exit(common.DRILL_EXIT)
                why = self._should_stop(item, started, est, limit_s)
                if why and stopped is None:
                    stopped = why
                    stop_file.write_text(why, encoding="utf-8")
                    common.log(self.out, f"{item['id']}: STOP ({why})")
                    grace = common.SMOKE_STOP_GRACE_S if self.smoke else common.STOP_GRACE_S
                    until = common.time.monotonic() + grace
                    while proc.poll() is None and common.time.monotonic() < until:
                        common.time.sleep(1)
                    if proc.poll() is None:
                        common.log(self.out, f"{item['id']}: ended by TerminateJobObject")
                        job.terminate()
                        proc.wait(30)
                self._periodic(item)
            codes.append(proc.returncode)
            walls.append(round(common.time.monotonic() - cmd_t0, 2))
            self.item_state(item["id"])["walls"] = walls
            leftover = processes.job_leftovers(job)
            if leftover:
                job.terminate()
                self.state.setdefault("leftovers", []).append({"when": item["id"], "pids": leftover,
                                                              "at": common.time.strftime("%H:%M:%S")})
            job.close()
            if stopped:
                cut = True
                if stopped.startswith("drift"):
                    return {"status": "pending", "note": "preempted by a drift probe", "exit": None,
                            "preempted": "drift", "codes": codes}
                if stopped.startswith("the PC has been in use"):
                    return {"status": "pending", "note": "stopped while the PC was in use; queued again",
                            "exit": None, "preempted": "in use", "codes": codes}
                break
        if self.monitor and item.get("timing") and not self.smoke and not self.fake:
            if self.monitor.noisy(noisy_t0):
                st = self.item_state(item["id"])
                if st.get("noisy_once"):
                    return {"status": "noisy", "codes": codes, "note": "noisy twice"}
                st["noisy_once"] = True
                return {"status": "noisy", "codes": codes, "note": "noisy"}
        if cut:
            return {"status": "cut", "codes": codes, "note": stopped}
        ok = all(code == 0 for code in codes)
        return {"status": "done" if ok else "failed", "codes": codes}

    def _should_stop(self, item, started, est, limit_s):
        elapsed = common.time.monotonic() - started
        if common.time.time() >= self.session["deadline_epoch"]:
            return "the deadline"
        if self._owner_stop():
            return "the owner's STOP file"
        if limit_s is not None and elapsed >= limit_s:
            return "its time is up"
        if item["priority"] > 0 and elapsed > common.OVERRUN * max(est, 60):
            return "overrun: past twice its estimate"
        if item.get("preemptible") and self._drift_due():
            return "drift probe due"
        if self.monitor and not self.smoke and not self.fake and item["block"] == "D" \
                and self.monitor.in_use_for(300, other_over=30.0):
            return "the PC has been in use for 5 minutes"
        return None

    # ---------------------------------------------------------------- periodic probes (section 7)

    def _in_d(self):
        return self.d_started is not None and not self.item_state("D9").get("status") == "done"

    def _drift_due(self):
        if not self._in_d():
            return False
        last = self.last["drift"] if self.last["drift"] is not None else self.d_started
        return common.time.monotonic() - last >= self.periods["drift"]

    def _check_monitor(self):
        """Start the monitor again if its thread stopped before the deadline (the gap is logged)."""
        if self.monitor is None or self.monitor.alive() or common.time.time() > self.session["deadline_epoch"]:
            return
        common.sys.path.insert(0, str(common.HERE))
        import overnight_monitor
        common.log(self.out, "The monitor had stopped: started again (its gap shows in cpu.csv).")
        self.state.setdefault("monitor_restarts", []).append(common.time.strftime("%H:%M:%S"))
        self.monitor = overnight_monitor.Monitor(self.out / "cpu.csv", job=self.job,
                                                 until=self.session["deadline_epoch"] + 1800)
        self.monitor.start()

    def _periodic(self, item):
        now = common.time.monotonic()
        if now - self.last.get("monitor", 0.0) >= 30:
            self.last["monitor"] = now
            self._check_monitor()
        if now - self.last["pids"] >= common.OWN_PIDS_S:
            self.record_pids()
            self.save()
        if not self._in_d() or self.fake:
            return
        if self.last["poll"] is None or now - self.last["poll"] >= self.periods["poll"]:
            self.last["poll"] = now
            self._pool_poll()
        if item.get("exclusive"):
            return
        last = self.last["soak"] if self.last["soak"] is not None else self.d_started
        if (self.probe_proc is None or self.probe_proc.poll() is not None) and now - last >= self.periods["soak"]:
            self.last["soak"] = now
            self._soak_probe()

    def _pool_poll(self):
        try:
            done = common.subprocess.run([common.PY, "-m", "decklab.lib.forge", "pool", "--json"], cwd=str(common.TREE),
                                  capture_output=True, text=True, timeout=60, env=self.env())
            found = common.json.loads(done.stdout or "[]")
        except (OSError, ValueError, common.subprocess.SubprocessError):
            return
        path = self.out / "mem.csv"
        new = not path.exists()
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("unix,service_pid,worker_pid,state,games,heap_mb\n")
            for service in found:
                for worker in ((service.get("status") or {}).get("workers") or []):
                    f.write(f"{int(common.time.time())},{service.get('pid')},{worker.get('pid')},{worker.get('state')},"
                            f"{worker.get('games')},{worker.get('heap_mb')}\n")

    def _soak_probe(self, final=False, commander=None):
        probes = self.out / "probes"
        probes.mkdir(parents=True, exist_ok=True)
        n = len(self.state.setdefault("probes", []))
        name = "final.json" if final else f"{n:02d}.json"
        constructed = 35 if not self.smoke else 3
        if commander is None:
            commander = self._commander_share(final)
        argv = [common.PY, "-m", "decklab.lib.forge", "soak-probe", "--server-port", str(common.SERVER_PORT),
                "--constructed", str(constructed), "--commander", str(commander), "--seed", str(n),
                "--out", str(probes / name), "--json"]
        staging = str(self.out / "staging" / "results")
        for logs, results in (("replay", staging), ("crn", staging), ("ladders", staging), ("field", staging),
                              ("filler", str(self.out / "D" / "filler" / "results"))):
            argv += ["--results-dir", results, "--logs-dir", str(self.out / "logs" / logs)]
        self.state["probes"].append({"n": n, "file": name, "commander": commander, "final": final,
                                     "started": common.time.strftime("%Y-%m-%dT%H:%M:%S"),
                                     "session": len(self.state["sessions"])})
        common.log(self.out, f"Soak probe {name} started.")
        proc = processes.start_child(argv, str(common.TREE), self.env(), probes / f"{name}.out.txt", self.job)
        self.save()
        if final:
            proc.wait()
            return proc.returncode
        self.probe_proc = proc
        return None

    def _commander_share(self, final):
        quota = 150 if not self.smoke else 2
        asked = sum(p.get("commander", 0) for p in self.state.get("probes", []))
        if final:
            return max(0, quota - asked)
        return min(max(0, quota - asked), 15 if not self.smoke else 1)

    def _drift_probe(self):
        if self.probe_proc is not None and self.probe_proc.poll() is None:
            try:
                self.probe_proc.wait(600)       # a drift probe runs alone
            except common.subprocess.TimeoutExpired:
                pass
        n = len(self.state.setdefault("drift", []))
        folder = self.out / "probes" / f"drift-{n}"
        argv = [common.PY, str(common.LEGS), "drift-probe", "--port", str(common.SERVER_PORT), "--out", str(folder),
                "--seed-base", "7", "--games", str(plan._smoke_games(200) if self.smoke else 200),
                "--warm-games", str(plan._smoke_games(100) if self.smoke else common.DRIFT_WARM_GAMES)]
        folder.mkdir(parents=True, exist_ok=True)
        t = common.time.monotonic()
        job = processes.Job()
        proc = processes.start_child(argv, str(common.TREE), self.env(), folder / "out.txt", job)
        proc.wait()
        job.terminate()
        job.close()
        noisy = self.monitor.noisy(t) if self.monitor and not self.smoke else False
        self.state["drift"].append({"n": n, "folder": folder.name, "code": proc.returncode, "noisy": noisy,
                                    "at_s": round(common.time.monotonic() - (self.d_started or t)),
                                    "session": len(self.state["sessions"])})
        self.last["drift"] = common.time.monotonic()
        common.log(self.out, f"Drift probe {n}: exit {proc.returncode}" + (" (noisy)" if noisy else ""))
        self.save()

    # ---------------------------------------------------------------- internal items

    def _fake_internal(self, item, folder):
        if item.get("internal") == "server-start":
            self.d_started = common.time.monotonic()
        if item.get("internal") in ("report", "cleanup"):
            return getattr(self, "_internal_" + item["internal"])(item, folder)
        return {"status": "done", "note": "fake"}

    def _internal_preflight(self, item, folder):
        # the 8642 server is stopped before the checks, so its pool's slots and workers are gone by
        # the time "no slot held" is checked
        was_running = processes._http_ok(8642)
        self.state["server_was_running"] = was_running
        self.save()
        if was_running and not self.smoke:
            common.subprocess.run([common.PY, "-m", "decklab.lib.homenet", "stop"], cwd=self.plan["main"], capture_output=True)
            common.time.sleep(5 if self.fake else 20)
        found = plan.preflight_checks(self.plan["main"], smoke=self.smoke)
        found["server_running"] = was_running
        (folder / "preflight.json").write_text(common.json.dumps(found, indent=1), encoding="utf-8")
        failed = [c["name"] for c in found["checks"] if c["ok"] is False and c.get("gate")]
        out = {"status": "done", "checks_failed": failed}
        if failed:
            out.update(mg1_failed=True, note="MG1: " + "; ".join(failed))
        return out

    def _internal_idle_gate(self, item, folder):
        if self.smoke:
            return {"status": "done", "note": "no idle gate in --smoke"}
        if self.state.get("no_idle_gate"):
            # the owner's choice (supervise --no-idle-gate): start at once; the pause rules still apply
            return {"status": "done", "note": "no idle gate (supervise --no-idle-gate)"}
        until = common.time.monotonic() + common.START_WAIT_S
        self.paused_since = common.time.monotonic()        # the start's wait isn't active time
        try:
            while common.time.monotonic() < until:
                common.time.sleep(60)
                if self._owner_stop():
                    return {"status": "failed", "note": "the owner's STOP file", "exit": common.EXIT_OWNER_STOP}
                if self.monitor.free_for(600, other_max=5.0, other_window=60):
                    return {"status": "done"}
            return {"status": "failed", "note": "the PC was never idle", "exit": common.EXIT_NEVER_IDLE}
        finally:
            self.paused_base += common.time.monotonic() - self.paused_since
            self.paused_since = None

    def _internal_staging(self, item, folder):
        staging = self.out / "staging" / "results"
        staging.mkdir(parents=True, exist_ok=True)
        real = common.Path(self.plan["main"]) / "decklab" / "data" / "forge" / "results"
        copied = copy_snapshot(real, staging, smoke=self.smoke)
        filler = self.out / "D" / "filler" / "results"
        filler.mkdir(parents=True, exist_ok=True)
        copy_snapshot(real, filler, smoke=self.smoke)
        try:
            done = common.subprocess.run([common.PY, "-m", "decklab.lib.forge", "replay", "--results-dir", str(staging),
                                   "--dry-run", "--json"], cwd=str(common.TREE), capture_output=True, text=True,
                                  timeout=600, env=self.env())
            dry = common.json.loads(done.stdout)
            (folder / "replay-dry-run.json").write_text(common.json.dumps(dry, indent=1), encoding="utf-8")
        except (OSError, ValueError, common.subprocess.SubprocessError):
            dry = None
        if dry and self.items.get("D1"):
            games = dry.get("games") or 0
            est = (dry.get("estimate_s") or games * 0.6) / 2.0       # the warm speed-up, 2.0 until B2
            self.items["D1"]["est_s"] = max(60.0, est)
            common.log(self.out, f"D1 replays {games:,} games, about {round(est / 60)} min (estimate).")
        self.session["needs_upfront"] = True
        self._upfront()
        return {"status": "done", "copied": copied, "replay_games": (dry or {}).get("games")}

    def _internal_monitor(self, item, folder):
        return {"status": "done", "note": "the monitor runs from the controller's start"}

    def _internal_server_start(self, item, folder):
        self.d_started = common.time.monotonic()
        if self.server is not None and self.server[0].poll() is None:
            return {"status": "done", "note": "already up"}
        env = self.env()
        env["DECKLAB_SEED_BASE"] = "2"
        job = processes.Job()
        proc = processes.start_child([common.PY, str(common.TREE / "decklab" / "server.py"), "--host", "127.0.0.1", "--port",
                            str(common.SERVER_PORT), "--no-update"], str(common.TREE), env, folder / "server-out.txt", job)
        self.server = (proc, job)
        self.state.setdefault("test_servers", {})[str(common.SERVER_PORT)] = {"pid": proc.pid}
        self.record_pids()
        for _ in range(60):
            if proc.poll() is not None:
                return {"status": "failed", "note": f"the test server exited ({proc.returncode})"}
            if processes._http_ok(common.SERVER_PORT):
                return {"status": "done"}
            common.time.sleep(1)
        return {"status": "failed", "note": "the test server didn't answer within 60 s"}

    def _internal_server_stop(self, item, folder):
        if self.probe_proc is not None and self.probe_proc.poll() is None:
            self.probe_proc.wait(600)
        common.subprocess.run([common.PY, str(common.TREE / "decklab" / "server.py"), "--stop", "--port", str(common.SERVER_PORT)],
                       cwd=str(common.TREE), capture_output=True, timeout=120)
        if self.server is not None:
            proc, job = self.server
            try:
                proc.wait(30)
            except common.subprocess.TimeoutExpired:
                job.terminate()
            job.close()
            self.server = None
        self.state.get("test_servers", {}).pop(str(common.SERVER_PORT), None)
        self.d_started = None
        return {"status": "done"}

    def _internal_filler(self, item, folder):
        """D-fill: the replay set again at seed base 5 into $OUT/D/filler/, while the soak minimum
        still owes time (and the budget allows), in pieces with probes between."""
        pieces, quick_failures = 0, 0
        template = [list(cmd) for cmd in item["cmds"]]
        while True:
            gen = self.state.get("filler_generation", 0)
            name = "results" if not gen else f"results-{gen}"
            cmds = [[c.replace("D/filler/results", f"D/filler/{name}") for c in cmd] for cmd in template]
            owed = self.filler_owed()
            left = self.remaining() - self.plan["end_reserve_s"] - sum(
                plan.item_est(i) for i in self._pending() if i["block"] in ("D", "E") and i["id"] != item["id"]
                and i.get("internal") != "filler")
            if owed <= 0 or left <= 60:
                break
            limit = min(owed + 30, left, common.FILLER_CHUNK_S if not self.smoke else 120)
            if self.fake:
                limit = min(limit, 2)
            t = common.time.monotonic()
            outcome = self._children(item, folder, cmds=cmds, limit_s=limit)
            took = common.time.monotonic() - t
            self._add_soak(item, took, t)
            pieces += 1
            self.save()
            if outcome.get("preempted") == "in use":
                self._wait_until_free(item)
            if self._drift_due():
                self._drift_probe()
            if outcome.get("status") == "failed" and took < 60:
                quick_failures += 1
                if quick_failures >= 3:
                    return {"status": "failed", "pieces": pieces, "note": "the filler's replay kept failing at once"}
                continue
            quick_failures = 0
            if outcome.get("status") == "done":
                # the replay had nothing left to play: start the filler set again from the snapshot
                gen += 1
                self.state["filler_generation"] = gen
                copy_snapshot(common.Path(self.plan["main"]) / "decklab" / "data" / "forge" / "results",
                              self.out / "D" / "filler" / f"results-{gen}", smoke=self.smoke)
                self.save()
            if self.fake and pieces >= 3:
                break
        return {"status": "done", "pieces": pieces, "note": None if pieces else "no filler needed"}

    def _internal_final_probe(self, item, folder):
        if self.fake:
            return {"status": "done"}
        if self.probe_proc is not None and self.probe_proc.poll() is None:
            self.probe_proc.wait()
        t0 = common.time.time() - 2
        code = self._soak_probe(final=True)
        return final_probe_outcome(code, self.out / "probes" / "final.json", t0)

    def _internal_cleanup(self, item, folder):
        if self.server is not None:
            self._internal_server_stop(item, folder)
        if self.monitor:
            self.monitor.stop()
            self.monitor = None         # MG12 is judged after the monitor stops; it stays stopped
        found = self._leftovers("end")
        own_java = [pid for pid, _ in processes.processes_named("java.exe") if self.job and self.job.contains(pid)
                    and pid != common.os.getpid()]
        foreign = [{"pid": pid, "command": None if self.fake else processes.command_line(pid)}
                   for pid, _ in processes.processes_named("java.exe") if not (self.job and self.job.contains(pid))]
        self.state["foreign_java"] = foreign
        user = common.TREE / "decklab" / "data" / "forge"
        deleted = 0
        for path in ([] if self.fake else user.rglob("forge*.log")):
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
        slots_held = [] if self.fake else processes._own_slots(self.job)
        clean = {"leftovers": found, "own_java": own_java, "foreign_java": foreign, "own_slots": slots_held,
                 "test_servers": self.state.get("test_servers", {}), "logs_deleted": deleted}
        (folder / "clean.json").write_text(common.json.dumps(clean, indent=1), encoding="utf-8")
        self.state["clean"] = clean
        if self.state.get("server_was_running") and not self.smoke:
            common.subprocess.run([common.PY, "-m", "decklab.lib.homenet", "start"], cwd=self.plan["main"], capture_output=True)
        return {"status": "done"}

    def _internal_report(self, item, folder):
        self.save()
        common.sys.path.insert(0, str(common.HERE))
        import overnight_report
        overnight_report.write(self.out)
        return {"status": "done"}


def final_probe_outcome(code, result_path, started_epoch):
    """D8's outcome from soak-probe's exit: 0 (all same) and 1 (differences found, judged by MG7)
    are done only when the probe wrote its result this time; exit 1 without one is soak-probe's
    refusal ("no live server pool on port 8643": the test server was down), which is a failure."""
    result_path = common.Path(result_path)
    try:
        written = result_path.stat().st_mtime >= started_epoch
    except OSError:
        written = False
    if code in (0, 1) and written:
        return {"status": "done", "probe_exit": code}
    if code == 1:
        text = ""
        try:
            text = common.Path(str(result_path) + ".out.txt").read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        why = "no live server pool on port 8643" if "no live server pool" in text else "it wrote no result"
        return {"status": "failed", "probe_exit": code, "note": f"soak-probe refused: {why}"}
    return {"status": "failed", "probe_exit": code}


def copy_snapshot(real, target, smoke=False):
    """Copy the real results folder's top-level results into target (A3). --smoke copies the two
    smallest Constructed results, each cut to its first 20 games, so replay plays a few games."""
    target = common.Path(target)
    target.mkdir(parents=True, exist_ok=True)
    paths = sorted(common.Path(real).glob("*.json"))
    if not smoke:
        for path in paths:
            common.shutil.copy2(path, target / path.name)
        return len(paths)
    picked = []
    for path in paths:
        try:
            data = common.json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("format") != "Constructed" or "seeds" in data:
            continue
        games = sum(len(b.get("games", [])) for b in data.get("batches", []))
        if games:
            picked.append((games, path, data))
    picked.sort(key=lambda x: x[0])
    for _, path, data in picked[:2]:
        kept, left = [], 20
        for batch in data.get("batches", []):
            if left <= 0:
                break
            batch = dict(batch, games=batch["games"][:left])
            left -= len(batch["games"])
            kept.append(batch)
        data["batches"] = kept
        (target / path.name).write_text(common.json.dumps(data), encoding="utf-8")
    return min(2, len(picked))
