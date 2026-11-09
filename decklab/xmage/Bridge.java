package decklab.xmage;

import com.google.gson.*;
import com.google.gson.stream.*;
import mage.cards.*;
import mage.cards.decks.Deck;
import mage.constants.*;
import mage.deck.Commander;
import mage.game.*;
import mage.game.match.Match;
import mage.game.match.MatchOptions;
import mage.game.mulligan.MulliganType;
import mage.player.ai.ComputerPlayer6;
import mage.player.ai.ComputerPlayer7;
import mage.players.Player;
import mage.util.RandomUtil;
import org.apache.log4j.*;
import org.apache.log4j.spi.LoggingEvent;

import java.io.*;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicBoolean;

/** One local AI-versus-AI game; no XMage server, sockets, GUI, household data or substitution. */
public final class Bridge {
    private static final String VERSION = "1.4.63-dev (2026-10-31 09-42)";
    private static final String REVISION = "79aec614fc29d0c3eebd10fff0d5c1b40852bd52";
    private static final String ENGINE = "596c4ca03d3be39230714bf28672543d30109c9c8eb8396d6f0ecdec20a67805";
    private static final String POLICY = "MAD/6/threads1/heap1024/activeProcessor1/London/0/casual20/commander40/21";
    private static final Gson JSON = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
    private static final PrintStream OUTPUT = System.out;
    private static final AtomicBoolean EMITTED = new AtomicBoolean();
    private static final Map<String, Object> RESULT = new LinkedHashMap<>();
    private static final EngineLog LOG = new EngineLog();

    private Bridge() { }

    public static void main(String[] arguments) {
        // Some upstream classes print diagnostics directly. Keep the protocol channel separate.
        System.setOut(System.err);
        RESULT.put("schema", 1);
        RESULT.put("engine", "xmage");
        RESULT.put("version", VERSION);
        RESULT.put("source_revision", REVISION);
        RESULT.put("engine_sha256", ENGINE);
        RESULT.put("reproducible", false);
        RESULT.put("ai", "MAD skill 6; one simulation thread");
        RESULT.put("coverage", new ArrayList<>());
        RESULT.put("games", new ArrayList<>());
        try {
            if (arguments.length != 1) throw new IllegalArgumentException("One request file is required.");
            Path requestFile = Paths.get(arguments[0]);
            if (Files.size(requestFile) > 1048576) throw new IllegalArgumentException("Request is too large.");
            byte[] bytes = Files.readAllBytes(requestFile);
            RESULT.put("request_sha256", sha(bytes));
            verifyInstallation();
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            JsonReader reader = new JsonReader(new StringReader(text));
            reader.setStrictness(Strictness.STRICT);
            JsonElement input = readJson(reader, 0);
            if (reader.peek() != JsonToken.END_DOCUMENT) throw new IllegalArgumentException("Trailing JSON data.");
            Request request = new Request(input.getAsJsonObject());
            RESULT.put("format", request.format);
            RESULT.put("seed", request.seed);
            RESULT.put("rules", request.format.equals("commander")
                    ? "commander-1v1-40-life-21-commander-damage-london-no-free-mulligan"
                    : "casual-1v1-20-life-no-format-or-ban-list-london-no-free-mulligan");
            Map<String, Object> gameResult = new LinkedHashMap<>();
            gameResult.put("arm", request.subject);
            gameResult.put("number", request.number);
            gameResult.put("seed", request.seed);
            gameResult.put("starting_player", request.starter);
            gameResult.put("status", "failed");
            gameResult.put("winner", null);
            gameResult.put("turns", 0);
            gameResult.put("errors", 0);
            RESULT.put("games", Collections.singletonList(gameResult));
            startWatchdog(request.timeout, gameResult);
            configureLogs();
            play(request, gameResult);
        } catch (IllegalArgumentException | IllegalStateException error) {
            RESULT.put("status", "invalid");
            RESULT.put("problem", "The request or installed bridge could not be verified.");
            System.err.println(error.getClass().getSimpleName() + ": " + error.getMessage());
        } catch (Throwable error) {
            RESULT.put("status", "failed");
            RESULT.put("problem", "XMage did not complete the game safely.");
            System.err.println(error.getClass().getSimpleName() + ": " + error.getMessage());
        }
        emit(RESULT);
        // MAD has a static executor. Exiting ends every simulation thread with this one game.
        System.exit(0);
    }

    private static synchronized void emit(Map<String, Object> result) {
        if (EMITTED.compareAndSet(false, true)) {
            OUTPUT.println(JSON.toJson(result));
            OUTPUT.flush();
        }
    }

    private static void startWatchdog(int seconds, Map<String, Object> game) {
        Thread watchdog = new Thread(() -> {
            try { Thread.sleep(seconds * 1000L); } catch (InterruptedException ignored) { return; }
            Map<String, Object> timeout = new LinkedHashMap<>();
            for (String key : Arrays.asList("schema", "engine", "version", "source_revision",
                    "engine_sha256", "identity_sha256", "bridge_sha256", "bridge_source_sha256", "request_sha256",
                    "format", "seed", "rules", "reproducible", "ai")) {
                if (RESULT.containsKey(key)) timeout.put(key, RESULT.get(key));
            }
            Map<String, Object> stopped = new LinkedHashMap<>(game);
            stopped.put("status", "timeout");
            stopped.put("winner", null);
            timeout.put("games", Collections.singletonList(stopped));
            timeout.put("coverage", Collections.emptyList());
            timeout.put("status", "timeout");
            timeout.put("problem", "XMage reached this game's time limit.");
            emit(timeout);
            System.exit(0);
        }, "DeckLab XMage watchdog");
        watchdog.setDaemon(true);
        watchdog.start();
    }

    private static void verifyInstallation() throws Exception {
        Path home = Paths.get(System.getProperty("decklab.xmage.home", "")).toRealPath();
        TreeMap<String, String> jars = new TreeMap<>();
        for (String directory : Arrays.asList("lib", "plugins")) {
            try (DirectoryStream<Path> stream = Files.newDirectoryStream(home.resolve(directory), "*.jar")) {
                for (Path file : stream) {
                    jars.put(home.relativize(file).toString().replace('\\', '/'), sha(file));
                }
            }
        }
        StringBuilder identity = new StringBuilder();
        jars.forEach((name, hash) -> identity.append(name).append('\0').append(hash).append('\n'));
        if (!ENGINE.equals(sha(identity.toString().getBytes(StandardCharsets.UTF_8)))) {
            throw new IllegalArgumentException("Installed XMage jars differ from the pinned release.");
        }
        Path artifact = Paths.get(Bridge.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        String actual = sha(artifact);
        if (!actual.equals(System.getProperty("decklab.xmage.bridge_sha256"))) {
            throw new IllegalArgumentException("Compiled bridge changed.");
        }
        RESULT.put("bridge_sha256", actual);
        String source = System.getProperty("decklab.xmage.source_sha256");
        RESULT.put("bridge_source_sha256", source);
        Path javaHome = Paths.get(System.getProperty("java.home"));
        String javaName = System.getProperty("os.name").startsWith("Windows") ? "java.exe" : "java";
        String javaSha = sha(javaHome.resolve("bin").resolve(javaName));
        String releaseSha = sha(javaHome.resolve("release"));
        String identitySha = sha(("decklab-xmage-v1\n" + ENGINE + "\n" + source + "\n" + actual
                + "\n" + javaSha + "\n" + releaseSha + "\n" + POLICY + "\n").getBytes(StandardCharsets.UTF_8));
        if (!identitySha.equals(System.getProperty("decklab.xmage.identity_sha256"))) {
            throw new IllegalArgumentException("XMage runtime identity changed.");
        }
        RESULT.put("identity_sha256", identitySha);
        if (!Boolean.getBoolean("java.awt.headless")) throw new IllegalArgumentException("Headless mode required.");
    }

    private static void configureLogs() {
        Logger root = Logger.getRootLogger();
        root.removeAllAppenders();
        Enumeration<?> loggers = LogManager.getCurrentLoggers();
        while (loggers.hasMoreElements()) ((Logger) loggers.nextElement()).removeAllAppenders();
        root.setLevel(Level.WARN);
        root.addAppender(LOG);
    }

    private static void play(Request request, Map<String, Object> record) throws Exception {
        long began = System.nanoTime();
        // The upstream executor has five fixed workers despite ActiveProcessorCount. Fence it to one.
        Field executor = ComputerPlayer6.class.getDeclaredField("threadPoolSimulations");
        executor.setAccessible(true);
        ThreadPoolExecutor pool = (ThreadPoolExecutor) executor.get(null);
        pool.setCorePoolSize(1);
        pool.setMaximumPoolSize(1);

        List<ExpansionSet> sets = new ArrayList<>(Sets.getInstance().values());
        sets.sort(Comparator.comparing(ExpansionSet::getCode));
        Map<String, Printing> catalogue = new HashMap<>();
        for (ExpansionSet set : sets) {
            if (set.getSetType().isCustomSet()) continue;
            if (request.format.equals("commander") && !set.getSetType().isEternalLegal()) continue;
            for (ExpansionSet.SetCardInfo info : set.getSetCardInfo()) {
                catalogue.putIfAbsent(info.getName(), new Printing(set.getCode(), info));
            }
        }
        List<Map<String, Object>> coverage = new ArrayList<>();
        Deck[] decks = new Deck[2];
        for (int side = 0; side < 2; side++) {
            decks[side] = loadDeck(request.decks.get(side).getAsJsonObject(), catalogue, request.format, coverage);
        }
        RESULT.put("coverage", coverage);
        if (decks[0] == null || decks[1] == null || LOG.errors > 0) {
            RESULT.put("status", "unsupported");
            record.put("status", "unsupported");
            return;
        }
        RandomUtil.setSeed(request.seed);
        Game game = request.format.equals("commander")
                ? new CommanderDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ALL,
                    MulliganType.LONDON.getMulligan(0), 40, 7)
                : new TwoPlayerDuel(MultiplayerAttackOption.LEFT, RangeOfInfluence.ALL,
                    MulliganType.LONDON.getMulligan(0), 60, 20, 7);
        Match match = new TwoPlayerMatch(new MatchOptions("Deck Lab cross-check", "Two Player Duel", false));
        Player[] players = new Player[2];
        for (int side = 0; side < 2; side++) {
            players[side] = new ComputerPlayer7(side == 0 ? "subject" : "opponent", RangeOfInfluence.ALL, 6);
            game.loadCards(decks[side].getCards(), players[side].getId());
            game.loadCards(decks[side].getSideboard(), players[side].getId());
            game.addPlayer(players[side], decks[side]);
            match.addPlayer(players[side], decks[side]);
        }
        GameOptions options = new GameOptions();
        options.rollbackTurnsAllowed = false;
        game.setGameOptions(options);
        game.setStartingPlayerId(players[request.starter].getId());
        game.start(game.getStartingPlayerId());
        int errors = game.getTotalErrorsCount() + LOG.errors;
        record.put("turns", game.getTurnNum());
        record.put("errors", errors);
        record.put("duration_seconds", (System.nanoTime() - began) / 1_000_000_000.0);
        record.put("starting_player", game.getStartingPlayerId().equals(players[0].getId()) ? 0 : 1);
        record.put("starting_life", game.getStartingLife());
        record.put("commanders", Arrays.asList(players[0].getCommandersIds().size(), players[1].getCommandersIds().size()));
        if (!game.hasEnded() || errors != 0 || LOG.thinkTimeouts != 0) {
            RESULT.put("status", "failed");
            record.put("status", "failed");
            RESULT.put("problem", "XMage reported an engine error or incomplete game.");
            return;
        }
        String winner;
        if (game.isADraw()) winner = "draw";
        else if (players[0].hasWon() && !players[1].hasWon()) winner = "subject";
        else if (players[1].hasWon() && !players[0].hasWon()) winner = "opponent";
        else throw new IllegalStateException("A finished game has no unambiguous winner.");
        record.put("winner", winner);
        record.put("status", "completed");
        RESULT.put("status", "completed");
    }

    private static Deck loadDeck(JsonObject input, Map<String, Printing> catalogue, String format,
                                 List<Map<String, Object>> coverage) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("deck_id", input.get("id").getAsString());
        List<String> missing = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        row.put("missing", missing);
        row.put("errors", errors);
        coverage.add(row);
        Deck deck = new Deck();
        for (String section : Arrays.asList("main", "commander")) {
            Set<Card> target = section.equals("main") ? deck.getCards() : deck.getSideboard();
            for (JsonElement element : input.getAsJsonArray(section)) {
                JsonObject requested = element.getAsJsonObject();
                String name = requested.get("name").getAsString();
                Printing printing = catalogue.get(name);
                if (printing == null && name.contains(" // ")) printing = catalogue.get(name.split(" // ", 2)[0]);
                if (printing == null) { missing.add(name); continue; }
                int quantity = requested.get("quantity").getAsInt();
                for (int number = 0; number < quantity; number++) {
                    Card card = CardImpl.createCard(printing.info.getCardClass(), new CardSetInfo(
                            printing.info.getName(), printing.set, printing.info.getCardNumber(),
                            printing.info.getRarity(), printing.info.getGraphicInfo()));
                    if (card == null || card.isNightCard() || !fullName(card).equals(name)) {
                        if (!missing.contains(name)) missing.add(name);
                        break;
                    }
                    target.add(card);
                }
            }
        }
        row.put("cards", deck.getCards().size() + deck.getSideboard().size());
        if (!missing.isEmpty()) { row.put("status", "unsupported"); return null; }
        if (format.equals("commander")) {
            Commander validator = new Commander();
            if (!validator.validate(deck)) errors.add(validator.getErrorsListInfo());
        } else {
            if (!deck.getSideboard().isEmpty()) errors.add("A casual deck cannot have commanders.");
            if (deck.getCards().size() < 60) errors.add("A casual deck needs at least 60 cards.");
            Map<String, Integer> counts = new HashMap<>();
            for (Card card : deck.getCards()) {
                if (!card.isBasic()) counts.merge(card.getName(), 1, Integer::sum);
            }
            for (Map.Entry<String, Integer> count : counts.entrySet()) {
                if (count.getValue() > 4) errors.add("More than four copies of " + count.getKey() + ".");
            }
        }
        row.put("status", errors.isEmpty() ? "supported" : "invalid");
        return errors.isEmpty() ? deck : null;
    }

    private static String fullName(Card card) {
        if (card instanceof CardWithHalves) {
            CardWithHalves halves = (CardWithHalves) card;
            return halves.getLeftHalfCard().getName() + " // " + halves.getRightHalfCard().getName();
        }
        if (card.getSecondCardFace() != null) return card.getName() + " // " + card.getSecondCardFace().getName();
        if (card.isFlipCard()) return card.getName() + " // " + card.getFlipCardName();
        return card.getName();
    }

    private static String sha(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(file)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static JsonElement readJson(JsonReader reader, int depth) throws IOException {
        if (depth > 12) throw new IllegalArgumentException("JSON is too deeply nested.");
        switch (reader.peek()) {
            case BEGIN_OBJECT:
                JsonObject object = new JsonObject();
                reader.beginObject();
                while (reader.hasNext()) {
                    String name = reader.nextName();
                    if (object.has(name)) throw new IllegalArgumentException("Duplicate JSON key.");
                    object.add(name, readJson(reader, depth + 1));
                }
                reader.endObject();
                return object;
            case BEGIN_ARRAY:
                JsonArray array = new JsonArray();
                reader.beginArray();
                while (reader.hasNext()) {
                    if (array.size() >= 2000) throw new IllegalArgumentException("JSON array is too large.");
                    array.add(readJson(reader, depth + 1));
                }
                reader.endArray();
                return array;
            case STRING: return new JsonPrimitive(reader.nextString());
            case NUMBER:
                String number = reader.nextString();
                if (!number.matches("-?(0|[1-9][0-9]*)")) throw new IllegalArgumentException("Integer values required.");
                return new JsonPrimitive(Long.parseLong(number));
            case BOOLEAN: return new JsonPrimitive(reader.nextBoolean());
            case NULL: reader.nextNull(); return JsonNull.INSTANCE;
            default: throw new IllegalArgumentException("Unexpected JSON token.");
        }
    }

    private static void keys(JsonObject object, Set<String> required, Set<String> optional) {
        if (!object.keySet().containsAll(required)) throw new IllegalArgumentException("Missing JSON fields.");
        for (String key : object.keySet()) {
            if (!required.contains(key) && !optional.contains(key)) throw new IllegalArgumentException("Unknown JSON field.");
        }
    }

    private static int integer(JsonObject object, String key, int minimum, int maximum) {
        JsonPrimitive value = object.getAsJsonPrimitive(key);
        if (!value.isNumber()) throw new IllegalArgumentException("Integer field required.");
        long number = value.getAsLong();
        if (number < minimum || number > maximum) throw new IllegalArgumentException("Integer field out of bounds.");
        return (int) number;
    }

    private static String string(JsonObject object, String key) {
        JsonPrimitive value = object.getAsJsonPrimitive(key);
        if (!value.isString()) throw new IllegalArgumentException("String field required.");
        String text = value.getAsString();
        if (text.isBlank() || text.length() > 200 || !text.equals(text.strip())
                || text.chars().anyMatch(c -> Character.isISOControl(c))) {
            throw new IllegalArgumentException("Invalid string field.");
        }
        return text;
    }

    private static final class Request {
        final String format;
        final String subject;
        final long seed;
        final int number;
        final int starter;
        final int timeout;
        final JsonArray decks;

        Request(JsonObject object) {
            keys(object, Set.of("schema", "format", "seed", "games", "timeout_seconds", "decks"),
                    Set.of("game_number", "starting_player"));
            integer(object, "schema", 1, 1);
            integer(object, "games", 1, 1);
            seed = integer(object, "seed", 0, Integer.MAX_VALUE);
            number = object.has("game_number") ? integer(object, "game_number", 1, 10000) : 1;
            starter = object.has("starting_player") ? integer(object, "starting_player", 0, 1) : (number - 1) % 2;
            timeout = integer(object, "timeout_seconds", 1, 600);
            format = string(object, "format");
            if (!Set.of("casual", "commander").contains(format)) throw new IllegalArgumentException("Unsupported format.");
            decks = object.getAsJsonArray("decks");
            if (decks.size() != 2) throw new IllegalArgumentException("Exactly two decks required.");
            for (JsonElement element : decks) {
                JsonObject deck = element.getAsJsonObject();
                keys(deck, Set.of("id", "main", "commander"), Collections.emptySet());
                string(deck, "id");
                Set<String> names = new HashSet<>();
                int total = 0;
                for (String section : Arrays.asList("main", "commander")) {
                    JsonArray rows = deck.getAsJsonArray(section);
                    if (section.equals("commander") && rows.size() > 2) throw new IllegalArgumentException("At most two commanders.");
                    for (JsonElement row : rows) {
                        JsonObject card = row.getAsJsonObject();
                        keys(card, Set.of("name", "quantity"), Collections.emptySet());
                        if (!names.add(string(card, "name"))) throw new IllegalArgumentException("Duplicate card rows.");
                        total += integer(card, "quantity", 1, section.equals("commander") ? 1 : 2000);
                    }
                }
                if (total < 1 || total > 2000) throw new IllegalArgumentException("Deck size out of bounds.");
            }
            subject = string(decks.get(0).getAsJsonObject(), "id");
            if (!Set.of("baseline", "variant").contains(subject)
                    || !string(decks.get(1).getAsJsonObject(), "id").equals("opponent")) {
                throw new IllegalArgumentException("Invalid deck roles.");
            }
        }
    }

    private static final class Printing {
        final String set;
        final ExpansionSet.SetCardInfo info;
        Printing(String set, ExpansionSet.SetCardInfo info) { this.set = set; this.info = info; }
    }

    private static final class EngineLog extends AppenderSkeleton {
        volatile int errors;
        volatile int thinkTimeouts;
        private int lines;
        @Override protected synchronized void append(LoggingEvent event) {
            if (event.getLevel().isGreaterOrEqual(Level.ERROR)) errors++;
            String message = event.getRenderedMessage();
            if (message.contains("AI player thinks too long")) thinkTimeouts++;
            if (lines++ < 40) System.err.println(event.getLevel() + " " + message.substring(0, Math.min(500, message.length())));
        }
        @Override public void close() { }
        @Override public boolean requiresLayout() { return false; }
    }
}
