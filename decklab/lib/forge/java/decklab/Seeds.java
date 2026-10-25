package decklab;

/*
 * Per-game seeds for Deck Lab's v2 engine: the same function as decklab/lib/forge/seeds.py
 * (whose docstring says what the numbers are), so Python can name the seed of any game a
 * chunk plays. Game g of a result is reseeded with gameSeed(base, stream, g):
 *     x = mix(base); x = mix(x ^ stream); x = mix(x ^ g)
 * mix being SplitMix64's output function (Steele, Lea and Flood, 2014), every number 64 bits
 * (Java's long arithmetic wraps exactly as seeds.py's masks do), and the top bit cleared, so
 * a seed is never negative (Forge's sim can't read "-s -5"). seeds.TEST_VECTORS holds
 * cases both must give; "java Seeds.java <base> <stream hex> <game> ..." prints them, which
 * the Python tests (test_forge_contract) compare when a JDK is installed.
 */
public final class Seeds {
    private Seeds() {}

    /** SplitMix64's output for state x. */
    public static long mix(long x) {
        long z = x + 0x9E3779B97F4A7C15L;
        z = (z ^ (z >>> 30)) * 0xBF58476D1CE4E5B9L;
        z = (z ^ (z >>> 27)) * 0x94D049BB133111EBL;
        return z ^ (z >>> 31);
    }

    /** Game g's seed: what MyRandom is reseeded with (new Random(seed)) before game g; 0 or more. */
    public static long gameSeed(long base, long stream, long game) {
        long x = mix(base);
        x = mix(x ^ stream);
        return mix(x ^ game) & Long.MAX_VALUE;
    }

    /** "loadseed" in ASCII: seeds.LOAD_SALT. */
    public static final long LOAD_SALT = 0x6C6F616473656564L;

    /** The seed loading game g's decks draws from (wave 3's deck-order-1): gameSeed(base, stream ^
     *  LOAD_SALT, game), seeds.load_seed's. */
    public static long loadSeed(long base, long stream, long game) {
        return gameSeed(base, stream ^ LOAD_SALT, game);
    }

    private static final java.util.regex.Pattern STREAM = java.util.regex.Pattern.compile("[0-9a-f]{16}");

    /** A stream as results store it and -dlgame gives it: 16 lower-case hex digits (unsigned),
     *  exactly what seeds.parse_stream takes (Long.parseUnsignedLong alone would also take a
     *  leading "+" and upper-case digits). */
    public static long parseStream(String hex) {
        if (hex == null || !STREAM.matcher(hex).matches()) {
            throw new NumberFormatException("a seed stream is 16 lower-case hex digits, not " + hex);
        }
        return Long.parseUnsignedLong(hex, 16);
    }

    /** For the tests: prints gameSeed(base, stream, game), one a line, for each "<base> <stream hex>
     *  <game>" of the arguments, in threes; with "load" first, loadSeed's instead. */
    public static void main(String[] args) {
        boolean load = args.length > 0 && args[0].equals("load");
        for (int i = load ? 1 : 0; i + 2 < args.length; i += 3) {
            long base = Long.parseLong(args[i]);
            long stream = parseStream(args[i + 1]);
            long game = Long.parseLong(args[i + 2]);
            System.out.println(load ? loadSeed(base, stream, game) : gameSeed(base, stream, game));
        }
    }
}
