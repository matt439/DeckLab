package decklab;

/*
 * DeckLabSim: Forge 2.0.15 "sim" mode plus a card-movement log (the card log, Deck Lab Milestone 8;
 * first written as Milestone 0's prototype, see decklab/forge-trial/logs.md), and since wave 2 the
 * start of serve mode (DeckLabServe).
 *
 *   DeckLabSim sim <Forge's sim arguments, and Deck Lab's own: Request>    one batch, then exit
 *   DeckLabSim serve                                                       a warm worker (DeckLabServe)
 *   DeckLabSim sim ... -t ...                                              Forge's own tournament mode
 *
 * The games are played by GameLoop (the same code in both modes), with the arguments Request
 * parses; this class holds the start-up and the card log's listener.
 *
 * Why the card log: Forge's game log (what `forge sim` prints without -q) never says which card
 * was drawn, what the opening hand was, or what was left in hand at the end. GameLogFormatter
 * (forge-game, tag forge-2.0.15) turns only Battlefield -> Graveyard/Exile zone changes into log
 * entries, and SimulateMatch already prints every entry type, so no flag or preference adds them.
 * Every zone change IS posted on the game's Guava EventBus as GameEventCardChangeZone
 * (GameAction.changeZone), including draws (Player.doDraw -> GameAction.moveTo). GameLoop is a
 * copy of SimulateMatch's single-match path that subscribes one extra listener (CardLog) to each
 * game (Game.subscribeToEvents, between Match.createGame and Match.startGame). The listener adds
 * INFORMATION entries to the game's own GameLog, so they print in order with Forge's lines:
 *
 *   Information: DL|log|1                                            first DL line of every game (format 1)
 *   Information: DL|deck|<seat>|<id>=<name>;<id>=<name>;...          once per player per game (main deck)
 *   Information: DL|commander|<seat>|<id>=<name>;...                 Commander games: right after that seat's deck
 *   Information: DL|zone|<turn>|<active seat>|<phase>|<from>|<to>|<owner seat>|<id>|<name>
 *   Information: DL|hand|<turn>|start|<seat>|<id>=<name>;...         at the start of turn 1 (kept hands)
 *   Information: DL|hand|<turn>|end|<seat>|<id>=<name>;...           after the game ends
 *   Information: DL|library|<turn>|end|<seat>|<count>                after the game ends
 *   Information: DL|error|<text>                                     the end-of-game lines couldn't be written
 *
 * The decks (library + hand, ids ascending) and commanders are written when Forge posts
 * GameEventGameStarted (GameAction.startGame): Match.startGame has then filled and shuffled every
 * library and put each commander in the command zone (Match.prepareAllZones), and no card has
 * been drawn yet. Zone changes before that are the game being set up and aren't logged, so
 * replaying the DL|zone lines from "deck ids in the library, commander ids in the command zone"
 * gives the end hands and library sizes.
 * Players are taken from Game.getRegisteredPlayers(): Game.getPlayers() drops a player as soon as
 * they lose (Game.onPlayerLost), which left the loser out of the end-of-game lines in the first
 * version of this class.
 * <turn> is Forge's turn counter (0 during mulligans), <phase> a PhaseType name or "-", zones are
 * ZoneType names or "-" (tokens are created from "-"). Seats are the N of "Ai(N)-<deck name>".
 * Deck-card names come from the card as it sat in the library at the start (front face; split cards
 * as "A // B"). The listener only reads game state and appends log entries; it doesn't touch the
 * RNG, so a seed replays the same games as Forge's own sim (checked 2026-09-29, see logs.md, and
 * by `python -m decklab.lib.forge cardlog-check` on each Forge version Deck Lab uses it with).
 *
 * Before Forge's header line each batch (and each serve request) also prints one DLENGINE| line
 * saying how its games are played (GameLoop.engineLine); readers of games never see it.
 *
 * Everything else (arguments, deck loading, AI profiles, seed, clock, output lines) is the same as
 * forge.view.SimulateMatch at tag forge-2.0.15; start-up is the same as forge.view.Main for "sim"
 * except that the Sentry crash reporter is not initialised. Tournament mode (-t) is handed to
 * Forge's own SimulateMatch unchanged (no card log).
 *
 * Deck Lab builds it (decklab/lib/forge/simjar.py) into
 * decklab/data/forge/cardlog/decklab-sim-<Forge version>-<stamp hash>.jar, from every .java file in
 * this folder (Deck Lab's changes to Forge's own classes are in Forge's jar: its fork's decklab branch):
 *   javac -cp <Forge folder>/forge-gui-desktop-<version>-jar-with-dependencies.jar -d <build folder> decklab/lib/forge/java/decklab/*.java ...
 *   jar --create --file decklab-sim-<version>-<hash>.jar -C <build folder> .
 * Run (cwd the Forge folder; -cp instead of -jar, so pass the jar manifest's Add-Opens as --add-opens):
 *   java <forge JVM flags> --add-opens ... -cp "<decklab-sim jar>;<forge jar>" decklab.DeckLabSim sim -D ... -d a.dck b.dck -n 20 -s 1
 * Deck Lab's runs (decklab/lib/forge/runner.py) and the trial's run_sim.py --card-log do all of this.
 */

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.google.common.eventbus.Subscribe;

import forge.GuiDesktop;
import forge.error.ExceptionHandler;
import forge.game.Game;
import forge.game.GameLog;
import forge.game.GameLogEntryType;
import forge.game.card.Card;
import forge.game.card.CardView;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventGameStarted;
import forge.game.event.GameEventTurnBegan;
import forge.game.phase.PhaseHandler;
import forge.game.player.Player;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.view.SimulateMatch;

public final class DeckLabSim {
    private DeckLabSim() {}

    public static void main(final String[] args) {
        // forge.view.Main, "sim" branch (Sentry left out)
        if (System.getProperty("java.awt.headless") == null) {
            System.setProperty("java.awt.headless", "true");
        }
        System.setProperty("java.util.Arrays.useLegacyMergeSort", "true");
        System.setProperty("sun.java2d.d3d", "false");
        GuiBase.setInterface(new GuiDesktop());
        ExceptionHandler.registerErrorHandling();
        GuiBase.logHWInfo();
        if (args.length > 0 && args[0].equals("serve")) {
            DeckLabServe.serve();       // exits when it's done
        } else if (Arrays.asList(args).contains("-t")) {
            SimulateMatch.simulate(args);
        } else {
            simulate(args);
        }
        System.out.flush();
        System.exit(0);
    }

    /** forge.view.SimulateMatch.simulate without the tournament branch: Forge started, then one
     *  request's games (GameLoop.play, every game: no Boundary). */
    static void simulate(String[] args) {
        FModel.initialize(null, null);
        Startup.afterInitialize(false);    // wave 3: AI profiles, AI patches, overrides hash
        WarmState.snapshot();

        System.out.println("Simulation mode");
        Request req = Request.parse(args);
        if (req == null) {
            return;
        }
        GameLoop.play(req, null);
        System.out.flush();
    }

    /** Listens to one game's events and writes card movements into its GameLog. */
    public static final class CardLog {
        /** The card log's format: the first DL line of every game is "DL|log|" + FORMAT. */
        static final int FORMAT = 1;
        private static final Pattern SEAT = Pattern.compile("^Ai\\((\\d+)\\)-");
        private final Game game;
        private final GameLog log;
        private final Map<Integer, String> deckNames = new HashMap<>();
        private boolean decksDumped = false;

        /** Made between Match.createGame and Match.startGame, so its line is the game's first. */
        CardLog(Game game) {
            this.game = game;
            this.log = game.getGameLog();
            add("DL|log|" + FORMAT);
        }

        private void add(String msg) {
            log.add(GameLogEntryType.INFORMATION, msg);
        }

        static String seat(String playerName) {
            if (playerName == null) {
                return "-";
            }
            Matcher m = SEAT.matcher(playerName);
            return m.find() ? m.group(1) : playerName;
        }

        private String turnPrefix() {
            PhaseHandler ph = game.getPhaseHandler();
            Player active = ph.getPlayerTurn();
            return ph.getTurn() + "|" + (active == null ? "-" : seat(active.getName())) + "|" + (ph.getPhase() == null ? "-" : ph.getPhase().name());
        }

        private String cardList(Iterable<Card> cards) {
            StringBuilder sb = new StringBuilder();
            for (Card c : cards) {
                if (sb.length() > 0) {
                    sb.append(';');
                }
                sb.append(c.getId()).append('=').append(deckNames.getOrDefault(c.getId(), c.getName()));
            }
            return sb.toString();
        }

        /** Record every player's main deck (library + hand) and, in Commander, their commanders, once:
         *  when the game starts (onGameStarted), before the first card is drawn. */
        private void dumpDecks() {
            decksDumped = true;
            boolean commander = game.getRules().hasCommander();
            for (Player p : game.getRegisteredPlayers()) {
                List<Card> cards = new ArrayList<>();
                for (Card c : p.getCardsIn(ZoneType.Library)) cards.add(c);
                for (Card c : p.getCardsIn(ZoneType.Hand)) cards.add(c);
                add("DL|deck|" + seat(p.getName()) + "|" + named(cards));
                if (commander) {
                    // The commanders themselves, not the whole command zone, which also holds Forge's effect cards.
                    add("DL|commander|" + seat(p.getName()) + "|" + named(new ArrayList<>(p.getCommanders())));
                }
            }
        }

        /** cardList of cards sorted by id, noting each one's name now for the later lines. */
        private String named(List<Card> cards) {
            cards.sort(Comparator.comparingInt(Card::getId));
            for (Card c : cards) {
                deckNames.put(c.getId(), c.getName());
            }
            return cardList(cards);
        }

        private void hands(String label) {
            for (Player p : game.getRegisteredPlayers()) {
                add("DL|hand|" + game.getPhaseHandler().getTurn() + "|" + label + "|" + seat(p.getName()) + "|" + cardList(p.getCardsIn(ZoneType.Hand)));
            }
        }

        void endOfGame() {
            if (!decksDumped) {
                dumpDecks();
            }
            hands("end");
            for (Player p : game.getRegisteredPlayers()) {
                add("DL|library|" + game.getPhaseHandler().getTurn() + "|end|" + seat(p.getName()) + "|" + p.getCardsIn(ZoneType.Library).size());
            }
        }

        /** GameAction.startGame posts this once Match.prepareAllZones has filled and shuffled every
         *  library and put the commanders in the command zone, and before the opening hands are drawn. */
        @Subscribe
        public void onGameStarted(GameEventGameStarted ev) {
            if (!decksDumped) {
                dumpDecks();
            }
        }

        @Subscribe
        public void onZoneChange(GameEventCardChangeZone ev) {
            if (!decksDumped) {
                return;     // the game being set up (Match.prepareAllZones), not a move in it
            }
            CardView c = ev.card();
            if (c == null) {
                return;
            }
            String from = ev.from() == null ? "-" : ev.from().zoneType().name();
            String to = ev.to() == null ? "-" : ev.to().zoneType().name();
            PlayerView owner = c.getOwner();
            String name = deckNames.get(c.getId());
            if (name == null) {
                name = c.getName();
            }
            add("DL|zone|" + turnPrefix() + "|" + from + "|" + to + "|" + seat(owner == null ? null : owner.getName()) + "|" + c.getId() + "|" + name);
        }

        @Subscribe
        public void onTurnBegan(GameEventTurnBegan ev) {
            if (ev.turnNumber() == 1) {
                if (!decksDumped) {
                    dumpDecks();
                }
                hands("start");
            }
        }
    }
}
