package decklab;

/*
 * Forge's state that outlives a game in one JVM, put back as a freshly started Forge has it, so a
 * warm worker (DeckLabServe) plays a request's games exactly as a new process would: the
 * investigation's prototype (sim-investigation/e3-profile/java/decklab/DeckLabServe.java), whose
 * 90 of 90 games were identical warm and fresh (e3 notes, "Determinism"), plus what v-r05 found
 * missing (Card.cp2card).
 *
 * snapshot() runs once, right after FModel.initialize (DeckLabSim.simulate and serve mode both
 * call it), and records the static id counters and the keys of Forge's static caches; reset()
 * puts them back and empties Forge's static AI state. Serve mode resets before every request; the
 * v2 loop (GameLoop.playGames) before every game. What's reset (the wave 2 contract's "Warm
 * state"; every class and field is named in the tables below, and nowhere else):
 *   COUNTERS      the 7 static id counters: SpellAbility, StaticAbility, ReplacementEffect,
 *                 SpellAbilityStackInstance, Game and Trigger maxId, CombatView nextId: their
 *                 values feed hashCode (Objects.hash(class, id)), so they order the HashSets and
 *                 HashMaps of abilities a game iterates (r2-engine notes, "(d)")
 *   KEYED_CACHES  Card.cp2card: taken back to the keys it had at snapshot()
 *   EMPTIED       ChangeZoneAi.multipleCardsToChoose: emptied
 *   and AiCache.clear().
 * The fields are found by name with reflection, so a Forge upgrade that renames one is found at
 * once: snapshot() then notes the problem (problem()) instead of throwing, sim mode's v1 games
 * (which never reset) play on, serve mode won't start (DLSERVE|fail), and reset() throws
 * IllegalStateException with it. reset() runs every game, so it stays cheap: 7 ints, one pass
 * over a map that holds a few cards, and two clears.
 *
 * Not reset, and not this class's: a game that crashed (an exception or StackOverflowError in
 * Match.startGame) may leave Forge's unsynchronised static lazy maps half updated
 * (Keyword.cardKeywordSetLookup, TrackableTypes.enumTypes, SpellApiToAi's instances), so serve
 * mode recycles after one (DeckLabServe.recycleReason) rather than repairing them; their contents
 * are otherwise the same whatever the history (a lookup per key). And the order of a HashSet or
 * HashMap of Cards or Players, which hash by identity: HotSpot seeds each thread's identity-hash
 * state when the thread is created, and a warm worker's game threads are created at other points
 * than a fresh process's, so that order can't be put back at all. Constructed games almost never
 * depend on it (e3: 90 of 90 the same, v-r08: 400 of 400); Commander games do (cli.LINE_FOR_LINE).
 * The warm-equivalence check (servecheck.py) is built around that.
 */

import java.lang.reflect.Field;
import java.util.Collection;
import java.util.ConcurrentModificationException;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

final class WarmState {
    private WarmState() {}

    /** The static id counters reset() puts back: {class, field}, each an int. */
    static final String[][] COUNTERS = {
        {"forge.game.spellability.SpellAbility", "maxId"},
        {"forge.game.staticability.StaticAbility", "maxId"},
        {"forge.game.replacement.ReplacementEffect", "maxId"},
        {"forge.game.spellability.SpellAbilityStackInstance", "maxId"},
        {"forge.game.Game", "maxId"},
        {"forge.game.combat.CombatView", "nextId"},
        {"forge.game.trigger.Trigger", "maxId"},
    };

    /**
     * Forge's static caches reset() takes back to the keys they had at snapshot(): {class, field},
     * each a Map. Card.cp2card (Card.getCardForUi) keeps, per PaperCard, a Card built with no game
     * the first time something asks for one; in a game that's CardView.getBackup (asked on every
     * state update of a double-faced, flip, adventure or cloned card: CardView.updateState) and a
     * merged (mutated) card's view. Building one takes ids from the counters above, so a fresh
     * process's game that meets such a card takes ids a warm worker already holding it doesn't
     * (v-r05). Taking out what games put in makes the worker build it again at the same point.
     * Not cleared outright: whatever start-up put there stays, as it does in a fresh process.
     */
    static final String[][] KEYED_CACHES = {
        {"forge.game.card.Card", "cp2card"},
    };

    /** Forge's static AI state reset() empties: {class, field}, each a Collection. */
    static final String[][] EMPTIED = {
        {"forge.ai.ability.ChangeZoneAi", "multipleCardsToChoose"},
    };

    private static Field[] fields;
    private static int[] snapshot;
    private static Map<?, ?>[] caches;
    private static Set<?>[] cacheKeys;
    private static Field[] emptied;
    private static String problem = "WarmState.snapshot() hasn't run";

    /** Record the counters and the caches' keys as they are now (right after FModel.initialize).
     *  Never throws. */
    static synchronized void snapshot() {
        try {
            Field[] found = new Field[COUNTERS.length];
            int[] values = new int[COUNTERS.length];
            for (int k = 0; k < COUNTERS.length; k++) {
                found[k] = field(COUNTERS[k]);
                values[k] = found[k].getInt(null);
            }
            Map<?, ?>[] maps = new Map<?, ?>[KEYED_CACHES.length];
            Set<?>[] keys = new Set<?>[KEYED_CACHES.length];
            for (int k = 0; k < KEYED_CACHES.length; k++) {
                maps[k] = (Map<?, ?>) field(KEYED_CACHES[k]).get(null);
                keys[k] = new HashSet<>(maps[k].keySet());
            }
            Field[] lists = new Field[EMPTIED.length];
            for (int k = 0; k < EMPTIED.length; k++) {
                lists[k] = field(EMPTIED[k]);
                if (!(lists[k].get(null) instanceof Collection)) {
                    throw new ClassCastException(EMPTIED[k][0] + "." + EMPTIED[k][1] + " isn't a collection");
                }
            }
            fields = found;
            snapshot = values;
            caches = maps;
            cacheKeys = keys;
            emptied = lists;
            problem = null;
        } catch (ReflectiveOperationException | RuntimeException e) {
            problem = "Forge's state can't be reset (" + e + ")";
        }
    }

    /** {class, field}'s field, made accessible. */
    private static Field field(String[] name) throws ReflectiveOperationException {
        Field f = Class.forName(name[0]).getDeclaredField(name[1]);
        f.setAccessible(true);
        return f;
    }

    /** Why reset() can't work, or null. */
    static synchronized String problem() {
        return problem;
    }

    /** Passes reset() makes over a cache's keys at most, when another thread changes them meanwhile. */
    static final int CACHE_TRIES = 3;

    /**
     * Put the counters and the caches back to the snapshot and empty Forge's static AI state.
     * Throws IllegalStateException, and only that, when it can't: snapshot() failed, or Forge's
     * state couldn't be put back (the v2 loop then ends its request with the reason, rather than
     * the process crashing). Forge's caches are plain HashMaps, and in a one-shot "sim -n K" the
     * game thread of a game the clock stopped may still be running, and adding to Card.cp2card,
     * while the next game resets: a pass over its keys that meets such a change is tried again,
     * CACHE_TRIES times in all. (Games after a clock stop count as unsure in the checks anyway;
     * serve mode never gets here after one, as it recycles.)
     */
    static synchronized void reset() {
        if (problem != null) {
            throw new IllegalStateException(problem);
        }
        try {
            for (int k = 0; k < fields.length; k++) {
                fields[k].setInt(null, snapshot[k]);
            }
            for (int k = 0; k < caches.length; k++) {
                for (int tries = 1; ; tries++) {
                    try {
                        caches[k].keySet().retainAll(cacheKeys[k]);
                        break;
                    } catch (ConcurrentModificationException e) {
                        if (tries == CACHE_TRIES) {
                            throw e;
                        }
                    }
                }
            }
            forge.ai.AiCache.clear();
            for (Field f : emptied) {
                // read every time: ChangeZoneAi's list isn't final, so Forge could swap it
                ((Collection<?>) f.get(null)).clear();
            }
        } catch (IllegalAccessException | RuntimeException e) {
            throw new IllegalStateException("Forge's state can't be reset (" + e + ")", e);
        }
    }

    /** The counters now, "a,b,c,...", for serve mode's ready line and for checks. */
    static synchronized String counters() {
        if (fields == null) {
            return "-";
        }
        StringBuilder sb = new StringBuilder();
        try {
            for (Field f : fields) {
                if (sb.length() > 0) {
                    sb.append(',');
                }
                sb.append(f.getInt(null));
            }
        } catch (IllegalAccessException e) {
            return "-";
        }
        return sb.toString();
    }
}
