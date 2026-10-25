package decklab;

/*
 * What a Deck Lab JVM does once, after Forge has started (FModel.initialize) and before WarmState
 * takes its snapshot (the wave 3 contract's section 3.4). DeckLabSim.simulate and DeckLabServe.serve
 * each call afterInitialize between the two:
 *   1. the AI profile folder: with -Ddecklab.aiprofiles=<dir>, Forge's profiles are loaded from that
 *      folder instead of res/ai (AiProfileUtil.loadAllProfiles; the folder holds copies of Forge's own
 *      *.ai and Deck Lab's, decklab/lib/forge/ai-profiles). A folder that can't be read, holds no
 *      profile, or has a key Forge doesn't know stops the JVM with exit code 3 (serve mode:
 *      "DLSERVE|fail|<why>"; sim mode: an "Error: <why>" line), so a pilot never falls back to
 *      another profile unseen.
 *   2. the AI patches (AiPatches.install), unless -Ddecklab.gamePatches=off or the test-only
 *      -Ddecklab.aipatches.install=false (J3's check that installing them changes no game).
 *   3. the overrides hash: the canonical hash of Forge's custom/cards folder (in the user folder,
 *      ForgeConstants.USER_CUSTOM_CARDS_DIR) as Forge loaded it at start-up (custom cards load eagerly
 *      in StaticData), for the DLENGINE line (overrides=). It's Python's engine._overrides and
 *      overrides.deployed_hash, byte for byte (the contract's section 6.4): every regular file at
 *      any depth, its path from that folder with "/", a NUL, the SHA-256 (hex) of its bytes with
 *      every CRLF made LF, and a newline, one per file in the paths' UTF-8 byte order; the SHA-256
 *      (hex) of all that, as UTF-8. "none" with no file (or no folder), "unreadable" when the folder
 *      or a file can't be read.
 *   4. deck-order-1's hook: DeckOrder.entries as forge.game.LibraryOrder's, which Forge's Match (Deck
 *      Lab's fork) asks for each library's order; Match passes it over with -Ddecklab.gamePatches=off.
 *      DeckOrder has an order only for the seats GameLoop gives it one.
 *   5. the AI switches' hook (AI round 1), whatever -Ddecklab.gamePatches says: Pilots.forkOn as
 *      forge.ai.AiSwitches' hook (setHook(BiPredicate<Player, String>)), so each of the fork's AI
 *      switches is on for the seats whose pilot names it (AiSwitches itself is always off with game
 *      patches off). Found by reflection: a fork build without AiSwitches (from before AI round 1)
 *      leaves it out, and Deck Lab's classes still compile and run against it.
 */

import java.io.File;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.function.BiPredicate;
import java.util.stream.Stream;

import forge.ai.AiProfileUtil;
import forge.game.LibraryOrder;
import forge.game.player.Player;
import forge.localinstance.properties.ForgeConstants;

final class Startup {
    private Startup() {}

    /** The overrides hash with no file: engine.NO_OVERRIDES. */
    static final String NO_OVERRIDES = "none";
    /** The overrides hash when the folder can't be read: engine.UNREADABLE_OVERRIDES. */
    static final String UNREADABLE = "unreadable";

    private static volatile boolean profileFolder = false;
    private static volatile String overrides = null;
    private static volatile boolean switchHook = false;

    /**
     * The start-up hooks (this class's comment), in order; serve says which mode is starting, for
     * how a failure is reported. Exits with code 3 when the AI profile folder can't be used.
     */
    static void afterInitialize(boolean serve) {
        String problem = loadProfiles(System.getProperty("decklab.aiprofiles"));
        if (problem != null) {
            if (serve) {
                DeckLabServe.say("fail|" + DeckLabServe.clean(problem));
            } else {
                System.out.println("Error: " + problem);
            }
            System.out.flush();
            System.exit(3);
        }
        if (!"off".equals(System.getProperty("decklab.gamePatches"))
                && !"false".equals(System.getProperty("decklab.aipatches.install"))) {
            AiPatches.install();
        }
        overrides = overridesHash(new File(ForgeConstants.USER_CUSTOM_CARDS_DIR).toPath());
        LibraryOrder.setHook(DeckOrder::entries);
        switchHook = installSwitchHook();
    }

    /** Is Pilots.forkOn forge.ai.AiSwitches' hook (step 5)? Request.parse refuses a fork switch if not. */
    static boolean switchHook() {
        return switchHook;
    }

    /** Step 5: Pilots.forkOn as forge.ai.AiSwitches' hook, when this Forge build has AiSwitches. */
    static boolean installSwitchHook() {
        BiPredicate<Player, String> hook = Pilots::forkOn;
        try {
            Class.forName("forge.ai.AiSwitches").getMethod("setHook", BiPredicate.class).invoke(null, hook);
            return true;
        } catch (ReflectiveOperationException | LinkageError e) {
            return false;       // a fork build from before AI round 1 (no AI switches), or one that can't load them
        }
    }

    /** Was a -Ddecklab.aiprofiles folder loaded (aiprofiles=dl), rather than Forge's res/ai (forge)? */
    static boolean profileFolder() {
        return profileFolder;
    }

    /** The overrides hash worked out at start-up (worked out now if start-up didn't run). */
    static String overrides() {
        String now = overrides;
        if (now == null) {
            now = overridesHash(new File(ForgeConstants.USER_CUSTOM_CARDS_DIR).toPath());
            overrides = now;
        }
        return now;
    }

    /** Load Forge's AI profiles from dir (null or empty: keep res/ai's); why it can't be used, or null. */
    static String loadProfiles(String dir) {
        if (dir == null || dir.isEmpty()) {
            return null;
        }
        String[] children = new File(dir).list();
        if (children == null) {
            return "the AI profile folder " + dir + " can't be read";
        }
        if (Arrays.stream(children).noneMatch(name -> name.endsWith(".ai"))) {
            return "the AI profile folder " + dir + " holds no AI profile";
        }
        try {
            AiProfileUtil.loadAllProfiles(dir);
        } catch (RuntimeException e) {
            return "the AI profile folder " + dir + " can't be loaded (" + e + ")";
        }
        profileFolder = true;
        return null;
    }

    /** The canonical hash of an overrides folder (this class's comment, step 3). */
    static String overridesHash(Path folder) {
        if (!Files.exists(folder)) {
            return NO_OVERRIDES;
        }
        List<String[]> files = new ArrayList<>();       // {path from folder with "/", its SHA-256}
        try (Stream<Path> walk = Files.walk(folder)) {
            for (Path p : (Iterable<Path>) walk::iterator) {
                if (Files.isRegularFile(p)) {
                    String name = folder.relativize(p).toString().replace(File.separatorChar, '/');
                    files.add(new String[] {name, sha256(lf(Files.readAllBytes(p)))});
                }
            }
        } catch (IOException | UncheckedIOException | SecurityException e) {
            return UNREADABLE;
        }
        if (files.isEmpty()) {
            return NO_OVERRIDES;
        }
        files.sort((a, b) -> Arrays.compareUnsigned(a[0].getBytes(StandardCharsets.UTF_8),
                b[0].getBytes(StandardCharsets.UTF_8)));
        StringBuilder text = new StringBuilder();
        for (String[] f : files) {
            text.append(f[0]).append('\0').append(f[1]).append('\n');
        }
        return sha256(text.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** data with every CRLF made LF. */
    static byte[] lf(byte[] data) {
        byte[] out = new byte[data.length];
        int n = 0;
        for (int i = 0; i < data.length; i++) {
            if (data[i] == '\r' && i + 1 < data.length && data[i + 1] == '\n') {
                continue;
            }
            out[n++] = data[i];
        }
        return Arrays.copyOf(out, n);
    }

    /** The SHA-256 of data, as 64 lower-case hex digits. */
    static String sha256(byte[] data) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder hex = new StringBuilder(64);
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);     // every JDK has SHA-256
        }
    }

    /** For the tests: prints overridesHash(<folder>) for each folder named. */
    public static void main(String[] args) {
        for (String folder : args) {
            System.out.println(overridesHash(Path.of(folder)));
        }
    }
}
