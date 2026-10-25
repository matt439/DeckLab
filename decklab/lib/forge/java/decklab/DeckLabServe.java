package decklab;

/*
 * Serve mode ("DeckLabSim serve"): a warm worker for Deck Lab's pool (decklab/lib/forge/pool.py).
 * It starts Forge once (FModel.initialize, WarmState.snapshot) and then plays requests read from
 * stdin, one at a time, each exactly as "DeckLabSim sim" with the same arguments would, through
 * the same GameLoop, after WarmState.reset(). The protocol is the wave 2 contract's "Serve protocol"
 * (version PROTOCOL); in short:
 *
 * stdin, one command a line, fields separated by tabs (no field holds a tab or a line break):
 *     play<TAB><id><TAB>sim<TAB><arg><TAB><arg>...    a request: sim's arguments, one a field
 *     cancel<TAB><id>                                 stop request <id> at its next game boundary
 *     quit                                            exit (a request playing stops at its next
 *                                                     game boundary first)
 * stdout, among Forge's own lines (a request's output is what sim prints after start-up):
 *     DLSERVE|ready|<protocol>|<pid>|<id counters>    once, when it can take requests
 *     DLSERVE|begin|<id>                              a request starts
 *     DLSERVE|end|<id>|<status>|<games>|<ms>|<detail> it ended: status done (every game played),
 *                                                     cancelled (stopped at a game boundary: a
 *                                                     cancel, quit or the end of stdin), recycle (a
 *                                                     game left a thread or Forge's state behind,
 *                                                     detail clock, ai_timeout or crash
 *                                                     (recycleReason): this worker exits next), or
 *                                                     error (no game could start: arguments that
 *                                                     can't be read, a deck or AI profile Forge
 *                                                     doesn't know; or Java failed: detail says why)
 *     DLSERVE|bye|<why>                               it exits next: quit, eof, recycle (exit code
 *                                                     0) or error (a Throwable escaped: exit code 1)
 *     DLSERVE|bad|<what>                              a command it doesn't understand (ignored)
 *     DLSERVE|fail|<why>                              it can't serve at all (exit code 3)
 * <id> is the pool's ([A-Za-z0-9._-], at most 64). <games> counts the request's "Game Result"
 * lines, <ms> its wall time. Fields after the status never hold "|" except <detail>, the last;
 * a done or cancelled request's detail is "heap_mb=<n>", the heap in use after the latest
 * garbage collection (heapAfterGcMb), so the pool can watch a long-lived worker's memory.
 *
 * Once it's ready, its output goes to stdout and stderr alone (Forge's ExceptionHandler copies
 * everything into the user folder's forge<N>.log too, which a long-lived worker would grow without
 * end), in the charset ExceptionHandler's streams use, so a request prints the very bytes a
 * one-shot sim prints.
 *
 * A request is played as a one-shot sim plays the same arguments: WarmState.reset() first (and
 * the v2 loop resets before each game), then what DeckLabSim.simulate does after start-up. What a
 * reset can't put back (the identity-hash order of Cards and Players, WarmState's comment) and
 * what a game may leave running (a clock-stopped game thread, a timed-out AI evaluation, a
 * crash's half-updated static maps) are why a request ends with recycle after such a game and
 * the worker exits: Deck Lab starts another when it needs one. servecheck.py checks, once per
 * Forge version (a leg of cardlog-check; "serve-check" alone), that a worker plays every game a
 * fresh process plays for the same arguments, after other matchups' requests too.
 */

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.MemoryType;
import java.lang.management.MemoryUsage;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Set;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.regex.Pattern;

import forge.ai.AiSignals;
import forge.model.FModel;

final class DeckLabServe {
    private DeckLabServe() {}

    static final int PROTOCOL = 1;
    static final String PREFIX = "DLSERVE|";
    static final Pattern ID = Pattern.compile("[A-Za-z0-9._-]{1,64}");

    private static final BlockingQueue<String[]> commands = new LinkedBlockingQueue<>();
    private static final Set<String> cancelled = ConcurrentHashMap.newKeySet();
    private static volatile String current = null;     // the request playing, or null
    private static volatile boolean leaving = false;    // quit or the end of stdin came

    static void say(String line) {
        System.out.println(PREFIX + line);
        System.out.flush();
    }

    /** Serve requests until quit, the end of stdin, a recycle or an error; never returns. */
    static void serve() {
        FModel.initialize(null, null);
        Startup.afterInitialize(true);    // wave 3: AI profiles, AI patches, overrides hash
        WarmState.snapshot();
        if (WarmState.problem() != null) {
            say("fail|" + clean(WarmState.problem()));
            System.exit(3);
        }
        untee();
        Thread reader = new Thread(DeckLabServe::readCommands, "DeckLab serve stdin");
        reader.setDaemon(true);
        reader.start();
        say("ready|" + PROTOCOL + "|" + ProcessHandle.current().pid() + "|" + WarmState.counters());
        while (true) {
            String[] command;
            try {
                command = commands.take();
            } catch (InterruptedException e) {
                command = new String[] {"eof"};
            }
            switch (command[0]) {
                case "play" -> play(command);
                case "quit" -> bye("quit", 0);
                case "eof" -> bye("eof", 0);
                default -> say("bad|" + clean(String.join(" ", command)));
            }
        }
    }

    /**
     * Point System.out and System.err straight at the process's stdout and stderr again.
     * ExceptionHandler.registerErrorHandling (DeckLabSim.main) set them to streams that copy every
     * byte into forge<N>.log as well, for the JVM's life: a warm worker's every game (25 to 34 KB
     * each), into a file Deck Lab deletes while it's open (runner._tidy_user_dir), so it would grow
     * unseen until the worker exits. The new streams encode as ExceptionHandler's do (new
     * PrintStream(out, true): Charset.defaultCharset(), UTF-8 with runner's -Dfile.encoding) and
     * flush the same way, so nothing a request prints changes.
     */
    private static void untee() {
        System.out.flush();
        System.err.flush();
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, Charset.defaultCharset()));
        System.setErr(new PrintStream(new FileOutputStream(FileDescriptor.err), true, Charset.defaultCharset()));
    }

    /** The stdin thread: cancel and quit act at once (at the next game boundary); play waits its turn. */
    private static void readCommands() {
        try (BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = in.readLine()) != null) {
                if (line.endsWith("\r")) {
                    line = line.substring(0, line.length() - 1);
                }
                if (line.isEmpty()) {
                    continue;
                }
                String[] fields = line.split("\t", -1);
                switch (fields[0]) {
                    case "cancel" -> {
                        if (fields.length == 2 && ID.matcher(fields[1]).matches()) {
                            cancelled.add(fields[1]);
                        } else {
                            say("bad|" + clean(line));
                        }
                    }
                    case "quit" -> {
                        leaving = true;
                        commands.add(fields);
                    }
                    default -> commands.add(fields);
                }
            }
        } catch (IOException e) {
            // stdin went away: as its end
        }
        leaving = true;
        commands.add(new String[] {"eof"});
    }

    private static void play(String[] command) {
        if (command.length < 4 || !ID.matcher(command[1]).matches() || !"sim".equals(command[2])) {
            say("bad|" + clean(String.join(" ", command)));
            return;
        }
        final String id = command[1];
        String[] args = Arrays.copyOfRange(command, 2, command.length);
        long t0 = System.nanoTime();
        current = id;
        say("begin|" + id);
        String status;
        String detail = "";
        int games = 0;
        boolean exit = false;
        try {
            if (stopping(id)) {
                status = "cancelled";
            } else {
                WarmState.reset();
                System.out.println("Simulation mode");
                Request req;
                try {
                    req = Request.parse(args);
                } catch (RuntimeException e) {
                    // A number that isn't one, an option without its value: nothing was played,
                    // so the worker goes on.
                    System.out.println("Error: " + e);
                    req = null;
                }
                if (req == null) {
                    status = "error";
                    detail = "the request's arguments can't be read";
                } else {
                    GameLoop.Played played = GameLoop.play(req, last -> recycleReason(last) == null && !stopping(id));
                    games = played.games;
                    String why = played.last == null ? null : recycleReason(played.last);
                    if (played.problem != null) {
                        status = "error";
                        detail = played.problem;
                    } else if (why != null) {
                        status = "recycle";
                        detail = why;
                        exit = true;
                    } else if (played.stoppedEarly) {
                        status = "cancelled";
                    } else {
                        status = "done";
                    }
                }
            }
        } catch (Throwable t) {
            t.printStackTrace(System.out);
            status = "error";
            detail = t.toString();
            exit = true;            // Forge's state may be half changed: start afresh
        }
        System.out.flush();
        current = null;
        cancelled.remove(id);
        if (detail.isEmpty()) {
            detail = "heap_mb=" + heapAfterGcMb();
        }
        say("end|" + id + "|" + status + "|" + games + "|" + (System.nanoTime() - t0) / 1_000_000 + "|" + clean(detail));
        if (exit) {
            if ("recycle".equals(status)) {
                bye("recycle", 0);
            }
            bye("error", 1);
        }
    }

    /**
     * Why this worker mustn't play on after game last, or null. Each leaves something of that
     * game behind that the next game, reseeded or not, could meet:
     *   clock        its clock stopped it: its game thread may still be running (and drawing from
     *                MyRandom, which the next game is reseeded with)
     *   ai_timeout   an AI evaluation timed out in it, or one is still running now (forge.ai.AiSignals:
     *                Forge's AiController counts them in Deck Lab's fork; Python also reads the
     *                "AI eval thread at timeout" lines)
     *   crash        an exception or StackOverflowError ended it, which may have left Forge's
     *                static maps half changed
     */
    static String recycleReason(GameLoop.GameRecord last) {
        if (last.clockStop) {
            return "clock";
        }
        if (last.aiTimeouts > 0 || AiSignals.LIVE_EVALS.get() > 0) {
            return "ai_timeout";
        }
        if (last.crashed) {
            return "crash";
        }
        return null;
    }

    /** The heap in use after the latest garbage collection, in MB (each heap pool's
     *  getCollectionUsage(), summed; 0 before the first): what a worker keeps between games,
     *  without forcing a collection (runner's JVM flags turn System.gc() off anyway). */
    static long heapAfterGcMb() {
        long used = 0;
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans()) {
            MemoryUsage usage = pool.getType() == MemoryType.HEAP ? pool.getCollectionUsage() : null;
            if (usage != null) {
                used += usage.getUsed();
            }
        }
        return used / (1024 * 1024);
    }

    /** Should request id stop at its next game boundary? */
    private static boolean stopping(String id) {
        return leaving || cancelled.contains(id);
    }

    private static void bye(String why, int code) {
        say("bye|" + why);
        System.exit(code);
    }

    /** text on one line, for a DLSERVE field. */
    static String clean(String text) {
        return text == null ? "" : text.replace('\r', ' ').replace('\n', ' ');
    }
}
