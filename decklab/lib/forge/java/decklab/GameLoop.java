package decklab;

/*
 * Playing one request's games: what "DeckLabSim sim" plays for its arguments, and what serve
 * mode (DeckLabServe) plays for each request, so the two can't drift apart.
 *
 * play() picks the loop:
 * - playBatch, the v1 engine (no -dlgame): forge.view.SimulateMatch's single-match path at tag
 *   forge-2.0.15, as DeckLabSim always played it: MyRandom seeded once with -s, the decks loaded
 *   and the players made, then one Match plays -n games (the loser of each game starts the next;
 *   Forge's auto-profile is set up in its first game only).
 * - playGames, the v2 engine (-dlgame; the wave 2 contract's "The v2 game loop"): every game
 *   stands alone. Before game i of the request (the result's game g = first + i): WarmState.reset(),
 *   MyRandom reseeded with Seeds.gameSeed(base, stream, g), then the decks loaded, a new GameRules
 *   and the players made, and a new Match for that one game, so a coin flip picks who starts and
 *   Forge's auto-profile is set up in every game. Game g so plays the same whatever was played
 *   before it in the JVM, and the same as plain Forge's "sim -n 1 -s <gameSeed(base, stream, g)>"
 *   with the same deck order (cardlog-check compares them).
 * Both print, for every game, Forge's game log (with the card log's DL| lines unless
 * -dlnocardlog) and its "Game Result" line, exactly as SimulateMatch does, and before Forge's
 * header line one DLENGINE| line (engineLine) saying how the games are played.
 *
 * Wave 3 (decklab/forge-trial/sim-wave3-contract.md sections 3.2 and 3.3): with game patches on and
 * Forge's deck-order-1 Match in play (deck-order-1 among gamePatchIds), a v2 game loads its decks from a
 * load seed of its own (Seeds.loadSeed), notes each seat's .dck [Main] order for Match (through forge.game.LibraryOrder)
 * (DeckOrder), and only then is reseeded with its game seed and gets its players, so loading the
 * decks can't shift the game's random numbers. Each seat's player is made with its pilot's AI profile
 * (-a) and switches (-dlpilot, Pilots): aisim-hybrid-1 gives the seat Forge's look-ahead AI.
 *
 * A Boundary (serve mode's) is asked before every game but the first whether to go on, with how
 * the game before went (its clock stop, crash and AI timeouts: forge.ai.AiSignals); sim mode passes none and
 * plays every game. A request's games are counted in Played.
 */

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.CodeSource;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.EnumSet;
import java.util.List;
import java.util.Random;
import java.util.TreeSet;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.apache.commons.lang3.time.StopWatch;

import forge.LobbyPlayer;
import forge.ai.AIOption;
import forge.ai.AiProfileUtil;
import forge.ai.AiSignals;
import forge.ai.LobbyPlayerAi;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.Game;
import forge.game.GameEndReason;
import forge.game.GameLogEntry;
import forge.game.GameLogEntryType;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.Spell;
import forge.gui.GuiBase;
import forge.localinstance.properties.ForgeConstants;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.util.Lang;
import forge.util.MyRandom;
import forge.util.TextUtil;
import forge.util.WordUtil;
import forge.util.storage.IStorage;
import forge.view.TimeLimitedCodeBlock;

final class GameLoop {
    private GameLoop() {}

    /** The first word of the line that says how a request's games are played (engineLine). */
    static final String ENGINE_PREFIX = "DLENGINE|";

    /** Forge's jar's list of Deck Lab's changes to its classes (the fork's decklab branch, forge-game's
     *  resources), "<class file> <id>" a line, id "-" for one that plays the same games, "#" a comment
     *  (simjar.FORGE_PATCH_LIST; gamePatchIds reads it). */
    static final String FORGE_PATCH_LIST = "decklab/forge-patches.txt";

    /** How one game went, for the Boundary. */
    static final class GameRecord {
        final int ordinal;          // the game's place in the request: 0, 1, 2...
        final long number;          // v2: the result's game number (first + ordinal); v1: -1
        final boolean clockStop;    // the clock (-c) stopped it ("Stopping slow match as draw")
        final boolean crashed;      // an exception or StackOverflowError ended it
        final int aiTimeouts;       // AI evaluations that timed out during it (AiSignals.AI_TIMEOUTS;
                                    // Forge's AiController in Deck Lab's fork counts them)

        GameRecord(int ordinal, long number, boolean clockStop, boolean crashed, int aiTimeouts) {
            this.ordinal = ordinal;
            this.number = number;
            this.clockStop = clockStop;
            this.crashed = crashed;
            this.aiTimeouts = aiTimeouts;
        }
    }

    /** Asked before each game but the first: false stops the request there. */
    interface Boundary {
        boolean another(GameRecord last);
    }

    /** What a request played. */
    static final class Played {
        int games;                  // games played (each with its "Game Result" line)
        boolean clockStop;          // a game's clock stopped it (its thread may still be running)
        boolean stoppedEarly;       // the Boundary stopped it before -n games
        String problem;             // why the request couldn't start or stopped: an AI profile or deck
                                    // Forge doesn't know, or (v2) a WarmState reset that failed
        GameRecord last;            // the last game played, or null
    }

    /** Play req's games: playGames for -dlgame (v2), else playBatch (v1). */
    static Played play(Request req, Boundary boundary) {
        return req.dlGame ? playGames(req, boundary) : playBatch(req, boundary);
    }

    /**
     * The v2 engine (-dlgame): the wave 2 contract's "The v2 game loop". For game i = 0, 1, 2...
     * of the request (the result's game g = first + i):
     *   1. the Boundary is asked (i > 0), and a no stops the request (stoppedEarly);
     *   2. WarmState.reset(), so g plays the same after any games in this JVM; when Forge's state
     *      can't be reset (its IllegalStateException), an "Error:" line, played.problem says why
     *      and no further game starts;
     *   3. MyRandom reseeded with Seeds.gameSeed(base, stream, g);
     *   4. a new GameRules, both decks loaded and their players made (lineup: in playBatch's order,
     *      with playBatch's calls; loading a deck can draw from MyRandom, so every game loads its
     *      own, after its reseed);
     *      with deck-order-1 (ordered(): game patches on and Forge's deck-order-1 Match in play), steps 3
     *      and 4 are instead: MyRandom reseeded with Seeds.loadSeed(base, stream, g); both decks
     *      loaded (decks) and each seat's .dck [Main] order noted (DeckOrder.set); MyRandom
     *      reseeded with Seeds.gameSeed(base, stream, g); then a new GameRules and the players
     *      (players), so a list that loads with other random draws (a card with several arts, say)
     *      still plays its game from the same game seed;
     *   5. (i = 0 only) the DLENGINE line and Forge's header line (its "seed" is the result's
     *      base), from game first's decks: they draw nothing from MyRandom, so the line's
     *      auto-profile flags and average mana values are those of the decks game first plays;
     *   6. a new Match for this one game: game 1 of its Match, so a coin flip picks who starts and
     *      Forge sets each AI's auto-profile up (PlayerControllerAi.setupAutoProfile, which a Match
     *      does in its first game only), every game;
     *   7. playOne: the game's log and "Game Result: Game <i + 1> ...".
     * A game whose clock stopped it, or with an AI timeout, may leave a thread behind that draws
     * from the next game's Random: serve mode's Boundary recycles the worker after it; here the
     * games go on (cardlog-check treats every later game of the process as unsure).
     */
    static Played playGames(Request req, Boundary boundary) {
        Played played = new Played();
        GameType type = gameType(req);
        DeckOrder.clear();
        Pilots.set(req.pilots);
        if (!knownProfiles(req, played)) {
            return played;
        }
        boolean ordered = ordered();
        GameRecord last = null;
        for (int i = 0; i < req.games; i++) {
            if (last != null && boundary != null && !boundary.another(last)) {
                played.stoppedEarly = true;
                break;
            }
            long number = req.firstGame + i;
            try {
                WarmState.reset();
            } catch (IllegalStateException e) {
                played.problem = e.getMessage();
                System.out.println("Error: " + played.problem);
                break;
            }
            GameRules rules;
            Lineup game;
            if (ordered) {
                MyRandom.setRandom(new Random(Seeds.loadSeed(req.seed, req.stream, number)));
                game = decks(req, type, played);
                if (game == null) {
                    break;
                }
                for (int seat = 1; seat <= game.decks.size(); seat++) {
                    DeckOrder.set(seat, DeckOrder.mainNames(req.decks().get(seat - 1), type, req.deckDir));
                }
                MyRandom.setRandom(new Random(Seeds.gameSeed(req.seed, req.stream, number)));
                rules = rules(req, type);
                players(req, type, game);
            } else {
                MyRandom.setRandom(new Random(Seeds.gameSeed(req.seed, req.stream, number)));
                rules = rules(req, type);
                game = lineup(req, type, played);
                if (game == null) {
                    break;
                }
            }
            clock(req, rules);
            if (i == 0) {
                System.out.println(engineLine(req, game, deckOrder(ordered, game.decks), ordered, "v=2", "seeds=game",
                        "base=" + req.seed, "stream=" + req.streamHex(), "first=" + req.firstGame));
                System.out.println(header(req, type, game));
            }
            last = playOne(new Match(rules, game.players, "Test"), i, number, req.gameLog, req.cardLog);
            count(played, last);
        }
        System.out.flush();
        return played;
    }

    /** The v1 engine: forge.view.SimulateMatch.simulate after its argument parsing (Request), without
     *  the tournament branch, with the card log and a Boundary. */
    static Played playBatch(Request req, Boundary boundary) {
        Played played = new Played();
        DeckOrder.clear();          // v1 keeps Forge's library order
        Pilots.set(null);           // and no pilot switches (-dlpilot needs -dlgame)
        if (req.seed != null) {
            MyRandom.setRandom(new Random(req.seed));
        }
        GameType type = gameType(req);
        GameRules rules = rules(req, type);
        if (!knownProfiles(req, played)) {
            return played;
        }
        Lineup lineup = lineup(req, type, played);
        if (lineup == null) {
            return played;
        }
        clock(req, rules);
        System.out.println(engineLine(req, lineup, "0,0", false, "v=1", "seeds=batch"));
        System.out.println(header(req, type, lineup));

        Match mc = new Match(rules, lineup.players, "Test");
        GameRecord last = null;
        if (req.matchSize != 0) {
            int iGame = 0;
            while (!mc.isMatchOver()) {
                if (last != null && boundary != null && !boundary.another(last)) {
                    played.stoppedEarly = true;
                    break;
                }
                last = playOne(mc, iGame, -1, req.gameLog, req.cardLog);
                count(played, last);
                iGame++;
            }
        } else {
            for (int iGame = 0; iGame < req.games; iGame++) {
                if (last != null && boundary != null && !boundary.another(last)) {
                    played.stoppedEarly = true;
                    break;
                }
                last = playOne(mc, iGame, -1, req.gameLog, req.cardLog);
                count(played, last);
            }
        }
        System.out.flush();
        return played;
    }

    private static void count(Played played, GameRecord game) {
        played.games++;
        played.clockStop |= game.clockStop;
        played.last = game;
    }

    /** -f's game type (Constructed without it), as SimulateMatch reads it. */
    private static GameType gameType(Request req) {
        return req.format() == null ? GameType.Constructed : GameType.valueOf(WordUtil.capitalize(req.format()));
    }

    /** A new GameRules for the request's games, as SimulateMatch makes its one (the clock is set
     *  later: clock). */
    private static GameRules rules(Request req, GameType type) {
        GameRules rules = new GameRules(type);
        rules.setAppliedVariants(EnumSet.of(type));
        if (req.matchSize != 0) {
            rules.setGamesPerMatch(req.matchSize);
        }
        return rules;
    }

    /** -c's clock, when given, on rules. */
    private static void clock(Request req, GameRules rules) {
        if (req.clock() != null) {
            rules.setSimTimeout(Integer.parseInt(req.clock()));
        }
    }

    /** Does Forge know every AI profile -a names? When it doesn't, Forge's line is printed and
     *  played.problem says which. */
    private static boolean knownProfiles(Request req, Played played) {
        if (req.aiProfiles != null) {
            for (String profile : req.aiProfiles) {
                if (!AiProfileUtil.getProfilesDisplayList().contains(profile)) {
                    System.out.println(TextUtil.concatNoSpace("Unknown AI profile - ", profile,
                            ". Available profiles: ", String.join(", ", AiProfileUtil.getProfilesDisplayList())));
                    played.problem = "Unknown AI profile - " + profile;
                    return false;
                }
            }
        }
        return true;
    }

    /** The request's decks as loaded, the players made for them, and the players' names as
     *  Forge's header line shows them ("Ai(1)-a [Default] vs Ai(2)-b [Default]"). */
    private static final class Lineup {
        final List<Deck> decks = new ArrayList<>();
        final List<RegisteredPlayer> players = new ArrayList<>();
        final StringBuilder names = new StringBuilder();
    }

    /**
     * Load the request's decks (-d, from -D) in SimulateMatch's order: deck 1, then its
     * RegisteredPlayer and AI player, then deck 2 and its player... Both loops make their
     * players here (playGames without deck-order-1), so they make them with the same calls in the
     * same order: loading a deck (a card with no set picks a printing) and making an AI player can
     * draw from MyRandom. null after printing Forge's "Could not load deck" line, with
     * played.problem set.
     */
    private static Lineup lineup(Request req, GameType type, Played played) {
        Lineup lineup = new Lineup();
        if (req.decks() == null) {
            return lineup;
        }
        for (String deck : req.decks()) {
            Deck d = load(req, type, played, deck);
            if (d == null) {
                return null;
            }
            lineup.decks.add(d);
            player(req, type, lineup, lineup.decks.size(), d);
        }
        return lineup;
    }

    /** deck-order-1's first half of lineup: the request's decks loaded in order, without players
     *  (players makes them, after the game's reseed). null as lineup gives it. */
    private static Lineup decks(Request req, GameType type, Played played) {
        Lineup lineup = new Lineup();
        if (req.decks() == null) {
            return lineup;
        }
        for (String deck : req.decks()) {
            Deck d = load(req, type, played, deck);
            if (d == null) {
                return null;
            }
            lineup.decks.add(d);
        }
        return lineup;
    }

    /** deck-order-1's second half of lineup: each loaded deck's RegisteredPlayer and AI player, in order. */
    private static void players(Request req, GameType type, Lineup lineup) {
        for (int i = 1; i <= lineup.decks.size(); i++) {
            player(req, type, lineup, i, lineup.decks.get(i - 1));
        }
    }

    /** One deck of the request, loaded; null after printing Forge's "Could not load deck" line. */
    private static Deck load(Request req, GameType type, Played played, String deck) {
        Deck d = deckFromCommandLineParameter(deck, type, req.deckDir);
        if (d == null) {
            System.out.println(TextUtil.concatNoSpace("Could not load deck - ", deck, ", match cannot start"));
            played.problem = "Could not load deck - " + deck;
        }
        return d;
    }

    /**
     * Seat i's (1, 2...) RegisteredPlayer and AI player for deck d, named "Ai(<i>)-<deck name>" (and
     * added to the header's names) with -a's profile for the seat. A seat whose pilot has
     * aisim-hybrid-1 (Pilots) gets Forge's look-ahead AI (AIOption.USE_HYBRID_SIMULATION), its
     * sleeve drawn from MyRandom exactly as the three-argument createAiPlayer draws it, so a seat
     * without the switch plays the same games as before.
     */
    private static void player(Request req, GameType type, Lineup lineup, int i, Deck d) {
        List<String> aiProfiles = req.aiProfiles;
        if (i > 1) {
            lineup.names.append(" vs ");
        }
        String profile = aiProfiles != null && aiProfiles.size() >= i ? aiProfiles.get(i - 1) : "";
        String name = TextUtil.concatNoSpace("Ai(", String.valueOf(i), ")-", d.getName());
        lineup.names.append(name);
        if (!profile.isEmpty()) {
            lineup.names.append(" [").append(profile).append("]");
        }
        RegisteredPlayer rp = type.equals(GameType.Commander) ? RegisteredPlayer.forCommander(d) : new RegisteredPlayer(d);
        if (Pilots.on(i, Pilots.HYBRID)) {
            // GamePlayerUtil.createAiPlayer(name, avatar, profile)'s draw, then its five-argument call
            final int sleeveCount = GuiBase.getInterface().getSleevesCount();
            final int sleeve = sleeveCount == 0 ? 0 : MyRandom.getRandom().nextInt(sleeveCount);
            rp.setPlayer(GamePlayerUtil.createAiPlayer(name, i - 1, sleeve, EnumSet.of(AIOption.USE_HYBRID_SIMULATION), profile));
        } else {
            rp.setPlayer(GamePlayerUtil.createAiPlayer(name, i - 1, profile));
        }
        lineup.players.add(rp);
    }

    /** Forge's header line: "Ai(1)-a [Default] vs Ai(2)-b [Default] - 10 games of Constructed seed 7"
     *  (v2: the seed is the result's base). */
    private static String header(Request req, GameType type, Lineup lineup) {
        StringBuilder sb = new StringBuilder(lineup.names);
        sb.append(" - ").append(Lang.nounWithNumeral(req.games, "game")).append(" of ").append(type);
        if (req.seed != null) {
            sb.append(" seed ").append(req.seed);
        }
        return sb.toString();
    }

    /**
     * The DLENGINE| line: how this request's games are played, as key=value fields after
     * ENGINE_PREFIX, separated by "|" (no value holds "|" or "="). Printed once per request, before
     * Forge's header line, so readers of games never see it (LogReader keeps it as its engine).
     * first: the loop's own fields ("v=1", "seeds=batch"; v2 adds base, stream and first). Then:
     *   perf=true|false        Spell.isPerformanceMode(): Forge's PERFORMANCE_MODE preference took
     *   cardlog=on|off         the card log's listener (-dlnocardlog: off)
     *   gamepatches=on|off     -Ddecklab.gamePatches (off: Deck Lab's changes to Forge's classes that
     *                          change games play Forge's own code; the wave 2 contract's "Game-changing patches")
     *   gamepatchids=a,b       the game-changing changes in play, by id (gamePatchIds; empty: none)
     *   autoprofile=a,b        seat 1's and seat 2's auto-profile flag, 1 or 0: Forge's own rule
     *                          (PlayerControllerAi.setupAutoProfile): the deck's name holds "Control",
     *                          or its average mana value (Deck.getAverageCMC, truncated) is over 3
     *   avgcmc=a,b             each seat's Deck.getAverageCMC()
     * Wave 3's (sim-wave3-contract.md section 3.5):
     *   deckorder=a,b          each seat's 1 when its library is built in its .dck line order
     *                          (deck-order-1 and DeckOrder.check), else 0 (deckOrder)
     *   ai=a,b                 each seat's AI profile, as its player got it (-a)
     *   pilots=a,b             each seat's pilot switches joined by "+", or "-" for none (-dlpilot)
     *   aiprofiles=forge|dl    Forge's res/ai, or a -Ddecklab.aiprofiles folder (Startup)
     *   overrides=none|<hash>  the canonical hash of custom/cards at start-up (Startup.overrides)
     *   loadseed=1|0           1 when the decks were loaded from the load seed (deck-order-1)
     */
    static String engineLine(Request req, Lineup lineup, String deckOrder, boolean loadSeed, String... first) {
        List<Deck> decks = lineup.decks;
        StringBuilder sb = new StringBuilder(ENGINE_PREFIX);
        for (String field : first) {
            sb.append(field).append('|');
        }
        sb.append("perf=").append(Spell.isPerformanceMode());
        sb.append("|cardlog=").append(req.cardLog ? "on" : "off");
        sb.append("|gamepatches=").append("off".equals(System.getProperty("decklab.gamePatches")) ? "off" : "on");
        sb.append("|gamepatchids=").append(gamePatchIds());
        StringBuilder flags = new StringBuilder();
        StringBuilder cmc = new StringBuilder();
        for (Deck d : decks) {
            int average = d.getAverageCMC();
            boolean flag = d.getName().contains("Control") || average > 3;
            if (flags.length() > 0) {
                flags.append(',');
                cmc.append(',');
            }
            flags.append(flag ? '1' : '0');
            cmc.append(average);
        }
        sb.append("|autoprofile=").append(flags).append("|avgcmc=").append(cmc);
        StringBuilder ai = new StringBuilder();
        for (int i = 0; i < lineup.players.size(); i++) {
            LobbyPlayer player = lineup.players.get(i).getPlayer();
            String profile = player instanceof LobbyPlayerAi ? ((LobbyPlayerAi) player).getAiProfile() : null;
            if (profile == null || profile.isEmpty()) {
                profile = req.aiProfiles != null && req.aiProfiles.size() > i ? req.aiProfiles.get(i) : "-";
            }
            ai.append(i > 0 ? "," : "").append(profile);
        }
        String pilots = req.pilots == null ? Pilots.NONE + "," + Pilots.NONE : String.join(",", req.pilots);
        sb.append("|deckorder=").append(deckOrder).append("|ai=").append(ai).append("|pilots=").append(pilots);
        sb.append("|aiprofiles=").append(Startup.profileFolder() ? "dl" : "forge");
        sb.append("|overrides=").append(Startup.overrides());
        sb.append("|loadseed=").append(loadSeed ? '1' : '0');
        return sb.toString();
    }

    /** The id of Deck Lab's change to Forge's Match (FORGE_PATCH_LIST): the library in .dck line order. */
    static final String DECK_ORDER = "deck-order-1";

    /** Does a v2 game here load its decks from the load seed and build libraries in .dck order: game
     *  patches on (no -Ddecklab.gamePatches=off) and Forge's deck-order-1 Match in play (gamePatchIds)? */
    static boolean ordered() {
        return !"off".equals(System.getProperty("decklab.gamePatches"))
                && Arrays.asList(gamePatchIds().split(",")).contains(DECK_ORDER);
    }

    /** The DLENGINE line's deckorder= for a request's decks: each seat's 1 when ordered and its
     *  .dck order applies to the deck as loaded (DeckOrder.check), else 0. */
    private static String deckOrder(boolean ordered, List<Deck> decks) {
        StringBuilder sb = new StringBuilder();
        for (int seat = 1; seat <= decks.size(); seat++) {
            sb.append(seat > 1 ? "," : "").append(ordered && DeckOrder.check(seat, decks.get(seat - 1)) ? '1' : '0');
        }
        return sb.toString();
    }

    /**
     * The ids of the game-changing changes to Forge's classes in play in this JVM, sorted, joined by
     * ","; "" for none. Forge's jar lists them (FORGE_PATCH_LIST); one counts only when its class was
     * loaded from the jar that holds the list, so a class path that put another copy of the class first
     * leaves its id out. The classes are loaded without being initialised, which changes nothing a game
     * does. With -Ddecklab.gamePatches=off the ids are still listed: the changes are in play, playing
     * Forge's own code.
     */
    static String gamePatchIds() {
        TreeSet<String> ids = new TreeSet<>();      // distinct: several classes may share an id
        ClassLoader loader = GameLoop.class.getClassLoader();
        URL list = loader.getResource(FORGE_PATCH_LIST);
        String listJar = list == null ? null : jarOf(list);
        if (listJar == null) {
            return "";
        }
        try (BufferedReader r = new BufferedReader(new InputStreamReader(list.openStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) {
                String[] parts = line.trim().split(" ");
                if (parts.length != 2 || !parts[0].endsWith(".class") || parts[1].equals("-")) {
                    continue;
                }
                String name = parts[0].substring(0, parts[0].length() - ".class".length()).replace('/', '.');
                try {
                    URL from = location(Class.forName(name, false, loader));
                    if (from != null && listJar.equals(from.toString())) {
                        ids.add(parts[1]);
                    }
                } catch (ClassNotFoundException | LinkageError e) {
                    // not loadable here: not in play
                }
            }
        } catch (IOException e) {
            return "";
        }
        return String.join(",", ids);
    }

    /** The jar a "jar:<jar URL>!/<entry>" resource URL is in, as its URL's text, or null for one that isn't in a jar. */
    private static String jarOf(URL resource) {
        String text = resource.toString();
        int bang = text.indexOf("!/");
        return text.startsWith("jar:") && bang > 0 ? text.substring("jar:".length(), bang) : null;
    }

    /** Where a class was loaded from (its jar), or null. */
    private static URL location(Class<?> c) {
        CodeSource source = c.getProtectionDomain().getCodeSource();
        return source == null ? null : source.getLocation();
    }

    /**
     * One game in mc: forge.view.SimulateMatch.simulateSingleMatch plus the CardLog listener
     * (unless cardLog is false), printing the game's log and its "Game Result" line. ordinal is
     * the game's place in the request (its "Game N" is ordinal + 1), number the result's game
     * number (v2) or -1 (v1).
     */
    static GameRecord playOne(final Match mc, int ordinal, long number, boolean outputGamelog, boolean cardLog) {
        final StopWatch sw = new StopWatch();
        sw.start();
        boolean clockStop = false;
        boolean crashed = false;
        final int timeoutsBefore = AiSignals.AI_TIMEOUTS.get();

        final Game g1 = mc.createGame();
        g1.setNoGUIUser();
        DeckLabSim.CardLog log = null;
        if (cardLog) {
            log = new DeckLabSim.CardLog(g1);
            g1.subscribeToEvents(log);
        }
        try {
            TimeLimitedCodeBlock.runWithTimeout(() -> {
                mc.startGame(g1);
                sw.stop();
            }, mc.getRules().getSimTimeout(), TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            clockStop = true;
            System.out.println("Stopping slow match as draw");
        } catch (Exception | StackOverflowError e) {
            crashed = true;
            e.printStackTrace();
        } finally {
            if (sw.isStarted()) {
                sw.stop();
            }
            g1.setGameOver(GameEndReason.Draw);
        }
        if (log != null) {
            try {
                log.endOfGame();
            } catch (RuntimeException e) {
                g1.getGameLog().add(GameLogEntryType.INFORMATION, "DL|error|end-of-game snapshot failed: " + e);
            }
        }

        List<GameLogEntry> entries = logEntries(g1, outputGamelog ? null : GameLogEntryType.MATCH_RESULTS);
        Collections.reverse(entries);
        for (GameLogEntry l : entries) {
            System.out.println(l);
        }

        if (g1.getOutcome().isDraw()) {
            System.out.printf("\nGame Result: Game %d ended in a Draw! Took %d ms.%n", 1 + ordinal, sw.getTime());
        } else {
            System.out.printf("\nGame Result: Game %d ended in %d ms. %s has won!\n%n", 1 + ordinal, sw.getTime(), g1.getOutcome().getWinningLobbyPlayer().getName());
        }
        return new GameRecord(ordinal, number, clockStop, crashed, AiSignals.AI_TIMEOUTS.get() - timeoutsBefore);
    }

    /**
     * The game's log entries of type (null: every type), newest first, as GameLog.getLogEntries
     * gives them. After a clock stop the abandoned game thread may still be adding entries to the
     * log (an ArrayList) while it's read, and a read that meets it can throw; it's tried a few
     * times, and then the game's lines are left out (its Game Result line still prints, so the
     * request goes on and serve mode's recycle still comes). An empty list changes nothing when
     * nothing throws, which is every game but such a one.
     */
    private static List<GameLogEntry> logEntries(Game game, GameLogEntryType type) {
        RuntimeException last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                List<GameLogEntry> entries = game.getGameLog().getLogEntries(type);
                if (!entries.contains(null)) {
                    return entries;
                }
            } catch (RuntimeException e) {
                last = e;
            }
        }
        System.out.println("Deck Lab: the game's log couldn't be read" + (last == null ? "" : " (" + last + ")"));
        return new ArrayList<>();
    }

    /** Copy of the private SimulateMatch.deckFromCommandLineParameter. */
    static Deck deckFromCommandLineParameter(String deckname, GameType type, String deckDir) {
        int dotpos = deckname.lastIndexOf('.');
        if (dotpos > 0 && dotpos == deckname.length() - 4) {
            String baseDir = deckDir != null ? deckDir : (type.equals(GameType.Commander) ?
                    ForgeConstants.DECK_COMMANDER_DIR : ForgeConstants.DECK_CONSTRUCTED_DIR);
            if (!baseDir.endsWith(File.separator)) {
                baseDir += File.separator;
            }
            File f = new File(baseDir + deckname);
            if (!f.exists()) {
                System.out.println("No deck found in " + baseDir);
            }
            return DeckSerializer.fromFile(f);
        }
        IStorage<Deck> deckStore = type.equals(GameType.Commander) ? FModel.getDecks().getCommander() : FModel.getDecks().getConstructed();
        return deckStore.get(deckname);
    }
}
