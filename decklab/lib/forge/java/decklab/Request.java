package decklab;

/*
 * One request's arguments: what "DeckLabSim sim ..." is given on the command line, and what
 * each "play" line of serve mode gives (DeckLabServe), parsed the way forge.view.SimulateMatch
 * parses them (at tag forge-2.0.15): each "-x" starts an option and the words after it are its
 * values. Forge's options:
 *     -D <deck folder> -d <deck 1>.dck <deck 2>.dck -n <games> -s <seed> -f <format>
 *     -c <clock seconds> -a <AI profile 1> <AI profile 2> [-q] [-m <games per match>]
 * Deck Lab's own (the wave 2 contract's "The request"):
 *     -dlgame <stream: 16 hex digits> <first game number>
 *                     the v2 engine: game i of the request (0, 1, 2...) is the result's game
 *                     first + i, reseeded with Seeds.gameSeed(seed, stream, first + i) and played
 *                     in a Match of its own (GameLoop.playGames); -s is then the result's base
 *     -dlnocardlog    play without the card log's listener (the v2 card-log check's "off" leg)
 *     -dlpilot <seat 1> <seat 2>
 *                     wave 3's pilot switches (v2 only): each seat's switch ids joined by "+", or
 *                     "-" for none (Pilots); a lone "-" is a value here, though SimulateMatch's
 *                     parser takes any other "-" word for a bad option
 * Parsing touches no game state and draws no random number, so it can happen before the seed
 * is set; GameLoop.play does everything in the order SimulateMatch does.
 */

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import forge.game.GameType;
import forge.util.WordUtil;

final class Request {
    final Map<String, List<String>> params;
    final String deckDir;           // -D, or null
    final int games;                // -n (1 when left out)
    final int matchSize;            // -m (0: play -n games)
    final boolean gameLog;          // the full game log (no -q)
    final Long seed;                // -s, or null; with -dlgame, the base
    final List<String> aiProfiles;  // -a, or null
    final boolean dlGame;           // -dlgame given: the v2 engine
    final long stream;              // -dlgame's stream (0 without it)
    final long firstGame;           // -dlgame's first game number (0 without it)
    final boolean cardLog;          // false with -dlnocardlog
    final String[] pilots;          // -dlpilot's values, each seat's switches ("-" for none): {"-", "-"} without it

    private Request(Map<String, List<String>> params, long stream, long firstGame, String[] pilots) {
        this.params = params;
        this.deckDir = params.containsKey("D") ? params.get("D").get(0) : null;
        this.games = params.containsKey("n") ? Integer.parseInt(params.get("n").get(0)) : 1;
        this.matchSize = params.containsKey("m") ? Integer.parseInt(params.get("m").get(0)) : 0;
        this.gameLog = !params.containsKey("q");
        this.seed = params.containsKey("s") ? Long.valueOf(Long.parseLong(params.get("s").get(0))) : null;
        this.aiProfiles = params.get("a");
        this.dlGame = params.containsKey("dlgame");
        this.stream = stream;
        this.firstGame = firstGame;
        this.cardLog = !params.containsKey("dlnocardlog");
        this.pilots = pilots;
    }

    /** The decks (-d), or null when none were given. */
    List<String> decks() {
        return params.get("d");
    }

    /** -f's value, or null (Constructed). */
    String format() {
        return params.containsKey("f") ? params.get("f").get(0) : null;
    }

    /** -c's value, or null (Forge's default clock). */
    String clock() {
        return params.containsKey("c") ? params.get("c").get(0) : null;
    }

    /** -dlgame's stream as results store it and the DLENGINE line shows it: 16 lower-case hex
     *  digits (Seeds.parseStream's form). */
    String streamHex() {
        return String.format("%016x", stream);
    }

    /**
     * The request for these arguments (args[0] is the mode, "sim", and is passed over), or null
     * after printing what's wrong. The words are split into options as SimulateMatch splits
     * them, with its checks: too few arguments (printed on stdout), a lone "-" or a value before
     * any option (on stderr); an empty argument throws StringIndexOutOfBoundsException, as it
     * does there. Without -dlgame, the values are then read as SimulateMatch reads them: a
     * number that isn't one throws NumberFormatException, and an option left without its value
     * IndexOutOfBoundsException (serve mode catches both and answers "error"). With -dlgame,
     * every value the request is read with is checked here first, and a problem is printed on
     * stdout as an "Error: -dlgame..." line and gives null: -dlgame's own values; -s missing or
     * not a whole number of 0 or more (Forge's parser reads "-s -5" as an option "-5", leaving
     * -s without a value); -n not a whole number from 1 to Integer.MAX_VALUE; -m (v2 plays
     * single games); -D without exactly one folder; -d without exactly two decks; -c not a whole
     * number of seconds from 1 to Integer.MAX_VALUE; and an -f that isn't one of Forge's game
     * types as GameLoop reads it ("commander" is Commander). An AI profile Forge doesn't know,
     * or a deck it can't load, is GameLoop's to report (Played.problem).
     * -dlpilot (wave 3) is checked the same way, giving an "Error: ..." line and null: not
     * exactly two values, without -dlgame, an id that isn't a switch (Pilots.available(): Deck
     * Lab's own and the fork's), team-pump-1 while -Ddecklab.gamePatches=off (its AI patch isn't
     * installed then) or when the patch couldn't be installed at start-up, and a fork switch when
     * Startup couldn't install its hook (Startup.switchHook).
     */
    static Request parse(String[] args) {
        if (args.length < 4) {
            System.out.println("Syntax: same as forge sim (see SimulateMatch)");
            return null;
        }
        final Map<String, List<String>> params = new HashMap<>();
        List<String> options = null;
        for (int i = 1; i < args.length; i++) {
            final String a = args[i];
            if (a.charAt(0) == '-' && !(a.equals(Pilots.NONE) && options != null && options == params.get("dlpilot"))) {
                if (a.length() < 2) {
                    System.err.println("Error at argument " + a);
                    return null;
                }
                options = new ArrayList<>();
                params.put(a.substring(1), options);
            } else if (options != null) {
                options.add(a);
            } else {
                System.err.println("Illegal parameter usage");
                return null;
            }
        }
        long stream = 0;
        long first = 0;
        List<String> dl = params.get("dlgame");
        if (dl != null) {
            if (dl.size() != 2) {
                System.out.println("Error: -dlgame needs a seed stream (16 hex digits) and a first game number");
                return null;
            }
            try {
                stream = Seeds.parseStream(dl.get(0));
                first = Long.parseLong(dl.get(1));
            } catch (NumberFormatException e) {
                System.out.println("Error: -dlgame " + String.join(" ", dl) + ": " + e.getMessage());
                return null;
            }
            if (first < 0) {
                System.out.println("Error: -dlgame's first game number must be 0 or more");
                return null;
            }
            if (number(params.get("s"), 0, Long.MAX_VALUE) == null) {
                System.out.println("Error: -dlgame needs -s, the result's seed base: a whole number of 0 or more");
                return null;
            }
            if (params.containsKey("n") && number(params.get("n"), 1, Integer.MAX_VALUE) == null) {
                System.out.println("Error: -dlgame's -n must be a whole number from 1 to " + Integer.MAX_VALUE);
                return null;
            }
            if (params.containsKey("m")) {
                System.out.println("Error: -dlgame plays single games, so it takes no -m");
                return null;
            }
            // Refused up front, so a value Forge can't read gives an Error: line instead of an
            // exception from the reads of it (the constructor's, or GameLoop's).
            if (params.containsKey("D") && params.get("D").size() != 1) {
                System.out.println("Error: -dlgame's -D must name one deck folder");
                return null;
            }
            List<String> decks = params.get("d");
            if (decks == null || decks.size() != 2) {
                System.out.println("Error: -dlgame plays two decks against each other, so -d needs two");
                return null;
            }
            if (params.containsKey("c") && number(params.get("c"), 1, Integer.MAX_VALUE) == null) {
                System.out.println("Error: -dlgame's -c must be a whole number of seconds from 1 to " + Integer.MAX_VALUE);
                return null;
            }
            if (params.containsKey("f") && !knownFormat(params.get("f"))) {
                System.out.println("Error: -dlgame's -f must be one of Forge's game types, such as Constructed or Commander");
                return null;
            }
        }
        String[] pilots = pilots(params.get("dlpilot"), dl != null);
        if (pilots == null) {
            return null;
        }
        return new Request(params, stream, first, pilots);
    }

    /** -dlpilot's values, each as Pilots.spec writes it ({"-", "-"} without it), or null after printing
     *  an "Error: ..." line (parse's checks). */
    private static String[] pilots(List<String> values, boolean v2) {
        if (values == null) {
            return new String[] {Pilots.NONE, Pilots.NONE};
        }
        if (values.size() != 2) {
            System.out.println("Error: -dlpilot needs each seat's switches (a + between ids, or - for none)");
            return null;
        }
        if (!v2) {
            System.out.println("Error: -dlpilot needs -dlgame");
            return null;
        }
        String[] out = new String[2];
        for (int seat = 0; seat < 2; seat++) {
            List<String> ids;
            try {
                ids = Pilots.parse(values.get(seat));
            } catch (IllegalArgumentException e) {
                System.out.println("Error: " + e.getMessage());
                return null;
            }
            if (ids.contains(Pilots.TEAM_PUMP)) {
                if ("off".equals(System.getProperty("decklab.gamePatches"))) {
                    System.out.println("Error: team-pump-1 needs game patches on");
                    return null;
                }
                if (!AiPatches.installed()) {
                    System.out.println("Error: team-pump-1's AI patch wasn't installed when this Forge started");
                    return null;
                }
            }
            for (String id : ids) {
                if (!Pilots.AVAILABLE.contains(id) && !Startup.switchHook()) {
                    System.out.println("Error: " + id + " needs the AI switch hook, which wasn't installed when "
                            + "this Forge started");
                    return null;
                }
            }
            out[seat] = Pilots.spec(ids);
        }
        return out;
    }

    /** Is -f's one value a format Forge's sim takes (GameType, as GameLoop reads it)? */
    private static boolean knownFormat(List<String> values) {
        if (values == null || values.size() != 1) {
            return false;
        }
        try {
            GameType.valueOf(WordUtil.capitalize(values.get(0)));
            return true;
        } catch (IllegalArgumentException | NullPointerException e) {
            return false;
        }
    }

    /** An option's one value as a whole number from min to max, or null (no value, more than
     *  one, not a number, or out of range). */
    private static Long number(List<String> values, long min, long max) {
        if (values == null || values.size() != 1) {
            return null;
        }
        try {
            long value = Long.parseLong(values.get(0));
            return value >= min && value <= max ? value : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
