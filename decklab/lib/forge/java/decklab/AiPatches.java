package decklab;

/*
 * Deck Lab's AI patches, installed at start-up without changing a Forge class (the wave 3 contract's
 * section 3.1; first written as the investigation's prototype, sim-investigation/r4-ai/java/decklab/
 * DeckLabAiPatches.java).
 *
 * SpellApiToAi (forge-ai SpellApiToAi.java) is an enum singleton whose private final EnumMap
 * apiToInstance caches one SpellAbilityAi per ApiType; get(api) fills it lazily. Putting Deck Lab's
 * instance in that map before the first game makes every later lookup (AiController.canPlaySa,
 * doTrigger, GameSimulator...) use it. Only the map's contents change, not a final field, so the
 * JDK's final-field rules (JEP 500) don't apply, and Forge's classes are on the class path (the
 * unnamed module), so setAccessible needs no --add-opens.
 *
 * install() puts TeamPumpAi in for ApiType.PumpAll once per JVM (Startup.afterInitialize calls it
 * when game patches are on) and prints "DL-START|aipatch|PumpAll" (a start-up line, before any game).
 * TeamPumpAi plays Forge's own PumpAllAi for every seat whose pilot lacks team-pump-1, so installing
 * it changes no game by itself. When it can't be installed (a Forge whose SpellApiToAi changed), a
 * "Deck Lab: ..." line says why, installed() stays false and Request.parse refuses team-pump-1.
 */

import java.lang.reflect.Field;
import java.util.Map;

import forge.ai.SpellAbilityAi;
import forge.ai.SpellApiToAi;
import forge.game.ability.ApiType;

public final class AiPatches {
    private AiPatches() {}

    /** The first word of a start-up line (printed before any request's output). */
    static final String START_PREFIX = "DL-START|";

    private static volatile boolean installed = false;

    /** Was TeamPumpAi installed in this JVM? */
    static boolean installed() {
        return installed;
    }

    /** Install the patches, once per JVM (later calls do nothing). */
    static synchronized void install() {
        if (installed) {
            return;
        }
        try {
            replace(ApiType.PumpAll, new TeamPumpAi());
            installed = true;
            System.out.println(START_PREFIX + "aipatch|PumpAll");
        } catch (ReflectiveOperationException | RuntimeException e) {
            System.out.println("Deck Lab: the team-pump AI patch couldn't be installed (" + e + ")");
        }
    }

    /** Put ai in SpellApiToAi's cache for api. */
    @SuppressWarnings("unchecked")
    private static void replace(ApiType api, SpellAbilityAi ai) throws ReflectiveOperationException {
        Field f = SpellApiToAi.class.getDeclaredField("apiToInstance");
        f.setAccessible(true);
        Map<ApiType, SpellAbilityAi> cache = (Map<ApiType, SpellAbilityAi>) f.get(SpellApiToAi.Converter);
        synchronized (cache) {
            cache.put(api, ai);
        }
    }
}
