package decklab;

/*
 * Pilot switches (the wave 3 contract's section 3.3): Deck Lab's changes to how Forge's AI plays one
 * seat, named per seat by a request's "-dlpilot <seat 1> <seat 2>" (v2 only), each a "+"-joined list
 * of switch ids, or "-" for none:
 *   team-pump-1      TeamPumpAi's alpha-strike logic for "creatures you control get +X/+Y" spells
 *                    (AiPatches installs it once per JVM with game patches on; it plays Forge's own
 *                    PumpAllAi for every seat without the switch)
 *   aisim-hybrid-1   Forge's own look-ahead AI (AIOption.USE_HYBRID_SIMULATION) for the seat's player,
 *                    which GameLoop makes with it
 * AVAILABLE must equal simjar.PILOT_SWITCHES' ids (a test holds them together). GameLoop calls set()
 * once per request (v1: no switches), and the AI asks on(player, id) during its games; a player's
 * seat is the N of its "Ai(N)-" name.
 *
 * AI round 1: the fork's own AI switches (forge.ai.AiSwitches, listed in Forge's jar as
 * decklab/ai-switches.txt) may be named too: available() is AVAILABLE and AiSwitches.ids(), read by
 * reflection, so this compiles and runs against a fork build without them (none then). Startup
 * plugs forkOn in as AiSwitches' hook, which Forge's AI asks on its hot paths (every
 * castSpellInMain1, every removal check in combat): forkOn answers false on one volatile read
 * (forkSwitches) unless the request playing names a fork switch for some seat.
 */

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.TreeSet;

import forge.game.player.Player;

public final class Pilots {
    private Pilots() {}

    static final String TEAM_PUMP = "team-pump-1";
    static final String HYBRID = "aisim-hybrid-1";

    /** Every switch id, sorted (simjar.PILOT_SWITCHES' ids). */
    static final List<String> AVAILABLE = List.of("aisim-hybrid-1", "team-pump-1");

    /** AVAILABLE and the fork's AI switches (available()), worked out once. */
    private static volatile List<String> available = null;

    /** Does the request playing name a fork switch (an id not in AVAILABLE) for some seat? */
    private static volatile boolean forkSwitches = false;

    /** "-": a seat with no switch. */
    static final String NONE = "-";

    /** Each seat's switches for the request playing ([seat 1's, seat 2's]), an immutable snapshot. */
    private static volatile List<List<String>> seats = List.of();

    /**
     * A -dlpilot value's switch ids, sorted (empty for "-"). IllegalArgumentException, with the
     * sentence Request.parse prints after "Error: ", for an id that isn't one of AVAILABLE.
     */
    static List<String> parse(String spec) {
        if (NONE.equals(spec)) {
            return List.of();
        }
        List<String> known = available();
        TreeSet<String> ids = new TreeSet<>();
        for (String id : spec.split("\\+", -1)) {
            if (!known.contains(id)) {
                throw new IllegalArgumentException("-dlpilot: no switch called " + id);
            }
            ids.add(id);
        }
        return List.copyOf(ids);
    }

    /**
     * Every switch id a request may name, sorted: AVAILABLE and the fork's (forge.ai.AiSwitches.ids(),
     * by reflection; none when this Forge build has no AiSwitches). Worked out once a JVM.
     */
    static List<String> available() {
        List<String> now = available;
        if (now == null) {
            TreeSet<String> ids = new TreeSet<>(AVAILABLE);
            try {
                Method method = Class.forName("forge.ai.AiSwitches").getMethod("ids");
                for (Object id : (List<?>) method.invoke(null)) {
                    ids.add(String.valueOf(id));
                }
            } catch (ReflectiveOperationException | ClassCastException | LinkageError e) {
                // a fork build from before AI round 1: Deck Lab's own switches only
            }
            now = List.copyOf(ids);
            available = now;
        }
        return now;
    }

    /** A seat's switches as the DLENGINE line and -dlpilot write them: joined by "+", or "-" for none. */
    static String spec(List<String> ids) {
        return ids == null || ids.isEmpty() ? NONE : String.join("+", ids);
    }

    /** The request's switches, a -dlpilot value per seat (null: none for any seat). */
    static void set(String[] perSeat) {
        List<List<String>> parsed = new ArrayList<>();
        boolean fork = false;
        if (perSeat != null) {
            for (String spec : perSeat) {
                List<String> ids = parse(spec);
                parsed.add(ids);
                for (String id : ids) {
                    fork |= !AVAILABLE.contains(id);
                }
            }
        }
        seats = Collections.unmodifiableList(parsed);
        forkSwitches = fork;
    }

    /** Is switch id on for seat (1, 2...)? */
    static boolean on(int seat, String id) {
        List<List<String>> now = seats;
        return seat >= 1 && seat <= now.size() && now.get(seat - 1).contains(id);
    }

    /**
     * AiSwitches' hook (Startup): is the fork's switch id on for this player's seat? False on one
     * volatile read while the request playing names no fork switch, before the seat is parsed.
     */
    public static boolean forkOn(Player player, String id) {
        if (!forkSwitches) {
            return false;
        }
        return on(player, id);
    }

    /** Is switch id on for this player's seat? */
    public static boolean on(Player player, String id) {
        if (player == null) {
            return false;
        }
        try {
            return on(Integer.parseInt(DeckLabSim.CardLog.seat(player.getName())), id);
        } catch (NumberFormatException e) {
            return false;       // not a Deck Lab player name
        }
    }
}
