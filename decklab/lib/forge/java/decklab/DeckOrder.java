package decklab;

/*
 * deck-order-1's library order (the wave 3 contract's section 3.2): each seat's library is built in
 * the request's .dck [Main] line order, copies expanded, instead of Forge's hash order, so a variant
 * list written in its base list's order (a new card in a removed copy's line) keeps every other card
 * in its place before the shuffle.
 *
 * GameLoop.playGames calls set(seat, names) for each seat after loading game g's decks (v2, game
 * patches on, deck-order-1 in the jar) and clear() at the start of every request, so v1 games and
 * requests without the patch never have an order. Startup plugs entries in as forge.game.LibraryOrder's
 * hook, which Forge's Match (Deck Lab's fork) asks with entries(player, section) when it builds a player's library. It finds the player's seat from the
 * "Ai(<n>)-" name prefix. arrange() groups the section's PaperCards by name (copies expanded; within
 * a name by art index, then edition, collector number and foil, so the order is fixed) and takes one
 * card per .dck name in line order. A name with no card left, or cards left over (an unsupported
 * card Forge's getValid took out, a name Forge rewrote), give null for that seat, and Forge's own
 * order plays. check(seat, deck) makes the same comparison once per request on the decks GameLoop
 * loaded, without changing them, so the DLENGINE line can say whether the order applies
 * (deckorder=); Python refuses a chunk where it doesn't.
 *
 * Names are matched as Deck Lab writes them (decklab/lib/forge/common.py forge_name and norm): the
 * front face of "A // B", accents taken off, any case. Nothing here draws a random number: making a
 * CardPool would (CardPool.add splits a card with several arts into random art groups), so the
 * comparison works on the section's entries.
 */

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.Normalizer;
import java.util.AbstractMap;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Map.Entry;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import forge.deck.Deck;
import forge.game.GameType;
import forge.game.player.Player;
import forge.item.PaperCard;
import forge.localinstance.properties.ForgeConstants;

public final class DeckOrder {
    private DeckOrder() {}

    /** Each seat's [Main] names (key()), copies expanded, in .dck line order: {seat ("1", "2"): names}. */
    private static final Map<String, List<String>> ORDER = new ConcurrentHashMap<>();

    /** Forge's keyword for a card taken out of a deck when the game isn't played for ante
     *  (Match.getRemovedAnteCards). */
    private static final String ANTE = "Remove CARDNAME from your deck before playing if you're not playing for ante.";

    /** A .dck line: "<count> <name>", the name possibly followed by "|<set>|<art>". */
    private static final Pattern LINE = Pattern.compile("^(\\d+)\\s*x?\\s+(.+)$");

    private static final Pattern MARKS = Pattern.compile("\\p{M}+");

    /** A seat's .dck [Main] names, in line order with copies expanded (null: no order for it). */
    static void set(int seat, List<String> names) {
        if (names == null) {
            ORDER.remove(String.valueOf(seat));
            return;
        }
        List<String> keys = new ArrayList<>(names.size());
        for (String name : names) {
            keys.add(key(name));
        }
        ORDER.put(String.valueOf(seat), Collections.unmodifiableList(keys));
    }

    /** No order for any seat: Forge's own library order. */
    static void clear() {
        ORDER.clear();
    }

    /**
     * The library for player from section in the seat's .dck order: one PaperCard per copy, or null
     * when the seat has no order or its names and section's cards don't match one for one.
     */
    public static List<PaperCard> arrange(Player player, Iterable<Entry<PaperCard, Integer>> section) {
        List<String> order = ORDER.get(DeckLabSim.CardLog.seat(player.getName()));
        return order == null ? null : match(order, section);
    }

    /**
     * What Forge's Match iterates to build a library (through forge.game.LibraryOrder): arrange()'s cards as (card, 1) entries in
     * order, or section itself when arrange() gives null.
     */
    public static Iterable<Entry<PaperCard, Integer>> entries(Player player, Iterable<Entry<PaperCard, Integer>> section) {
        List<PaperCard> cards = arrange(player, section);
        if (cards == null) {
            return section;
        }
        List<Entry<PaperCard, Integer>> out = new ArrayList<>(cards.size());
        for (PaperCard card : cards) {
            out.add(new AbstractMap.SimpleImmutableEntry<>(card, 1));
        }
        return out;
    }

    /**
     * Will the seat's order apply to deck (as loaded, before Match takes out its unsupported and ante
     * cards, which are left out here the same way)? False when the seat has no order.
     */
    static boolean check(int seat, Deck deck) {
        List<String> order = ORDER.get(String.valueOf(seat));
        if (order == null || deck == null || deck.getMain() == null) {
            return false;
        }
        List<Entry<PaperCard, Integer>> playable = new ArrayList<>();
        for (Entry<PaperCard, Integer> e : deck.getMain()) {
            if (playable(e.getKey())) {
                playable.add(e);
            }
        }
        return match(order, playable) != null;
    }

    /** Is card left in a library by Match.prepareAllZones (not unsupported, not an ante card)? */
    private static boolean playable(PaperCard card) {
        if (card.getRules() == null) {
            return true;
        }
        if (card.getRules().isUnsupported()) {
            return false;
        }
        for (String keyword : card.getRules().getMainPart().getKeywords()) {
            if (ANTE.equals(keyword)) {
                return false;
            }
        }
        return true;
    }

    /** One card per name of order, in order, or null when a name has no card left or cards are left over. */
    private static List<PaperCard> match(List<String> order, Iterable<Entry<PaperCard, Integer>> cards) {
        Map<String, List<PaperCard>> byName = new HashMap<>();
        for (Entry<PaperCard, Integer> e : cards) {
            List<PaperCard> copies = byName.computeIfAbsent(key(e.getKey().getName()), k -> new ArrayList<>());
            for (int i = 0; i < e.getValue(); i++) {
                copies.add(e.getKey());
            }
        }
        Map<String, Deque<PaperCard>> left = new HashMap<>();
        for (Entry<String, List<PaperCard>> e : byName.entrySet()) {
            List<PaperCard> copies = e.getValue();
            copies.sort(PRINTING);
            left.put(e.getKey(), new ArrayDeque<>(copies));
        }
        List<PaperCard> out = new ArrayList<>(order.size());
        for (String name : order) {
            Deque<PaperCard> copies = left.get(name);
            if (copies == null || copies.isEmpty()) {
                return null;
            }
            out.add(copies.removeFirst());
        }
        for (Deque<PaperCard> copies : left.values()) {
            if (!copies.isEmpty()) {
                return null;
            }
        }
        return out;
    }

    /** Copies of one name in a fixed order: art index, then edition, collector number and foil. */
    private static final Comparator<PaperCard> PRINTING = Comparator
            .comparingInt(PaperCard::getArtIndex)
            .thenComparing(c -> String.valueOf(c.getEdition()))
            .thenComparing(c -> String.valueOf(c.getCollectorNumber()))
            .thenComparing(PaperCard::isFoil);

    /** A card name as it's matched: the front face of "A // B", accents taken off, lower case. */
    static String key(String name) {
        if (name == null) {
            return "";
        }
        int split = name.indexOf(" // ");
        String front = split >= 0 ? name.substring(0, split) : name;
        return MARKS.matcher(Normalizer.normalize(front, Normalizer.Form.NFD)).replaceAll("")
                .toLowerCase(Locale.ROOT).trim();
    }

    /**
     * The [Main] names of the .dck file a request's -d names (as GameLoop.deckFromCommandLineParameter
     * finds it), in line order with copies expanded; null when it isn't a .dck file or can't be read.
     */
    static List<String> mainNames(String deckname, GameType type, String deckDir) {
        int dotpos = deckname.lastIndexOf('.');
        if (dotpos <= 0 || dotpos != deckname.length() - 4) {
            return null;
        }
        String baseDir = deckDir != null ? deckDir : (type.equals(GameType.Commander)
                ? ForgeConstants.DECK_COMMANDER_DIR : ForgeConstants.DECK_CONSTRUCTED_DIR);
        if (!baseDir.endsWith(File.separator)) {
            baseDir += File.separator;
        }
        try {
            return mainNames(Files.readAllLines(new File(baseDir + deckname).toPath(), StandardCharsets.UTF_8));
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /** The [Main] names of a .dck file's lines, in order, with copies expanded. */
    static List<String> mainNames(List<String> lines) {
        List<String> names = new ArrayList<>();
        boolean main = false;
        for (String raw : lines) {
            String line = raw.strip();
            if (line.startsWith("﻿")) {
                line = line.substring(1).strip();
            }
            if (line.startsWith("[") && line.endsWith("]")) {
                main = line.substring(1, line.length() - 1).strip().equalsIgnoreCase("main");
                continue;
            }
            if (!main || line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            int copies = 1;
            String name = line;
            Matcher m = LINE.matcher(line);
            if (m.matches()) {
                copies = Integer.parseInt(m.group(1));
                name = m.group(2);
            }
            int bar = name.indexOf('|');
            if (bar >= 0) {
                name = name.substring(0, bar);
            }
            name = name.strip();
            for (int i = 0; i < copies; i++) {
                names.add(name);
            }
        }
        return names;
    }
}
