package decklab;

/*
 * The team-pump-1 pilot switch (the wave 3 contract's sections 3.1 and 3.3; first written as the
 * investigation's prototype, sim-investigation/r4-ai/java/decklab/TeamPumpAi.java, r4 notes 2.2): a
 * replacement for Forge's PumpAllAi for "creatures you control get +X/+Y" team pumps (Overrun, Rabbit
 * Response, Warren Elder's ability, Make a Stand...), for the seats whose pilot has the switch.
 *
 * Forge's PumpAllAi.checkApiLogic (forge-ai PumpAllAi.java:131-133) casts a team pump only if
 * ComputerUtilCard.shouldPumpCard says yes for SOME SINGLE creature. For a sorcery that test is
 * "this creature is already in the AI's predicted attack" (ComputerUtilCard.java:1522-1528), and the
 * predicted attack (AiController.getPredictedCombat) is made without the pump, so on a stalled board
 * nothing "attacks" and Overrun is never cast. In combat the lethal check adds the pump to one
 * attacker only (ComputerUtilCard.java:1745-1764). This class adds up the whole team first:
 *
 *  1. Own turn, before attackers: estimate an alpha strike with every creature that can attack,
 *     pumped, against the opponent's untapped blockers (the opponent blocks the biggest attackers,
 *     one blocker each; trample carries over the blocker's toughness). Cast if it's lethal, or if it
 *     adds at least half the opponent's life with 3+ attackers (sorcery-speed pumps only).
 *  2. Own turn, after blockers: cast if the pumped unblocked/trample damage is lethal, or the pump adds
 *     at least a third of the opponent's life.
 *  3. Opponent's turn, after blockers: cast if it saves 2+ of our blockers.
 * Otherwise, and on any RuntimeException, Forge's own logic decides (super.checkApiLogic), so nothing
 * it casts today is lost. A seat without the switch (Pilots.on) gets Forge's logic alone, so with no
 * seat switched on the games are Forge's.
 *
 * Installed by AiPatches.install() (reflection into SpellApiToAi's instance cache) at start-up, with
 * game patches on; no Forge class is changed.
 */

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import forge.ai.AiAbilityDecision;
import forge.ai.AiPlayDecision;
import forge.ai.ComputerUtilCard;
import forge.ai.ComputerUtilCombat;
import forge.ai.SpellAbilityAi;
import forge.ai.ability.PumpAllAi;
import forge.game.Game;
import forge.game.ability.AbilityUtils;
import forge.game.card.Card;
import forge.game.combat.Combat;
import forge.game.combat.CombatUtil;
import forge.game.keyword.Keyword;
import forge.game.phase.PhaseHandler;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;

public class TeamPumpAi extends PumpAllAi {

    @Override
    protected AiAbilityDecision checkApiLogic(final Player ai, final SpellAbility sa) {
        if (!Pilots.on(ai, Pilots.TEAM_PUMP)) {
            return super.checkApiLogic(ai, sa);         // Forge's own logic, unchanged
        }
        try {
            if (isOwnTeamPump(sa) && teamPumpWorthIt(ai, sa)) {
                return new AiAbilityDecision(100, AiPlayDecision.WillPlay);
            }
        } catch (RuntimeException e) {
            // never let the switch break a game: Forge's logic decides
        }
        return super.checkApiLogic(ai, sa);
    }

    private static boolean isOwnTeamPump(SpellAbility sa) {
        return !sa.isCurse() && !sa.usesTargeting() && sa.getParamOrDefault("ValidCards", "").contains("YouCtrl")
                && sa.hasParam("NumAtt");
    }

    private static boolean teamPumpWorthIt(final Player ai, final SpellAbility sa) {
        final Game game = ai.getGame();
        final PhaseHandler ph = game.getPhaseHandler();
        final Card source = sa.getHostCard();
        final Player opp = ai.getWeakestOpponent();
        if (opp == null || !game.getStack().isEmpty()) {
            return false;   // responses to the stack: Forge's pumpAgainstRemoval handles those
        }
        final int power = AbilityUtils.calculateAmount(source, sa.getParam("NumAtt"), sa);
        final int defense = sa.hasParam("NumDef") ? AbilityUtils.calculateAmount(source, sa.getParam("NumDef"), sa) : 0;
        final List<String> keywords = sa.hasParam("KW") ? Arrays.asList(sa.getParam("KW").split(" & ")) : new ArrayList<>();
        final String valid = sa.getParamOrDefault("ValidCards", "");
        final int life = opp.getLife();
        if (life <= 0) {
            return false;
        }

        // 1. alpha strike before attackers are declared
        if (ph.isPlayerTurn(ai) && ph.getPhase().isBefore(PhaseType.COMBAT_DECLARE_ATTACKERS) && power > 0) {
            List<Card> mine = new ArrayList<>();
            List<Card> pumped = new ArrayList<>();
            for (Card c : ai.getCreaturesInPlay()) {
                if (c.isValid(valid, ai, source, sa) && CombatUtil.canAttack(c, opp)) {
                    mine.add(c);
                    pumped.add(ComputerUtilCard.getPumpedCreature(ai, sa, c, defense, power, keywords));
                }
            }
            if (mine.size() < 2) {
                return false;
            }
            List<Card> blockers = new ArrayList<>();
            for (Card b : opp.getCreaturesInPlay()) {
                if (CombatUtil.canBlock(b)) {
                    blockers.add(b);
                }
            }
            int with = alphaDamage(pumped, blockers, opp);
            if (with >= life) {
                return true;
            }
            int without = alphaDamage(mine, blockers, opp);
            return SpellAbilityAi.isSorcerySpeed(sa, ai) && mine.size() >= 3 && with - without >= Math.max(4, life / 2);
        }

        final Combat combat = game.getCombat();
        if (combat == null || !ph.is(PhaseType.COMBAT_DECLARE_BLOCKERS)) {
            return false;
        }

        // 2. our attack, blockers declared
        if (ph.isPlayerTurn(ai) && power > 0) {
            int now = 0;
            int extra = 0;
            for (Card a : combat.getAttackers()) {
                if (!a.getController().equals(ai)) {
                    continue;
                }
                int base = combatDamage(a, combat, opp);
                now += base;
                if (a.isValid(valid, ai, source, sa)) {
                    Card p = ComputerUtilCard.getPumpedCreature(ai, sa, a, defense, power, keywords);
                    extra += Math.max(0, combatDamage(p, a, combat, opp) - base);
                }
            }
            return now + extra >= life || extra >= Math.max(3, life / 3);
        }

        // 3. we're blocking: count blockers the pump saves
        if (!ph.isPlayerTurn(ai) && defense > 0) {
            int saved = 0;
            for (Card b : ai.getCreaturesInPlay()) {
                if (!combat.isBlocking(b) || !b.isValid(valid, ai, source, sa)) {
                    continue;
                }
                if (!ComputerUtilCombat.blockerWouldBeDestroyed(ai, b, combat)) {
                    continue;
                }
                int incoming = 0;
                for (Card a : combat.getAttackersBlockedBy(b)) {
                    incoming += a.getNetCombatDamage();
                }
                if (b.getNetToughness() + defense - b.getDamage() > incoming) {
                    saved++;
                }
            }
            return saved >= 2;
        }
        return false;
    }

    /** Damage to the opponent if they block the biggest attackers one-for-one with their toughest blockers. */
    private static int alphaDamage(List<Card> attackers, List<Card> blockers, Player opp) {
        List<Card> atk = new ArrayList<>(attackers);
        atk.sort(Comparator.comparingInt(Card::getNetCombatDamage).reversed());
        List<Card> blk = new ArrayList<>(blockers);
        blk.sort(Comparator.comparingInt(Card::getNetToughness).reversed());
        int dmg = 0;
        for (int i = 0; i < atk.size(); i++) {
            Card a = atk.get(i);
            int unblocked = ComputerUtilCombat.damageIfUnblocked(a, opp, null, false);
            if (i < blk.size()) {
                boolean evades = !CombatUtil.canBlock(a, blk.get(i));
                if (evades) {
                    dmg += unblocked;
                } else if (a.hasKeyword(Keyword.TRAMPLE)) {
                    dmg += Math.max(0, unblocked - blk.get(i).getNetToughness());
                }
            } else {
                dmg += unblocked;
            }
        }
        return dmg;
    }

    private static int combatDamage(Card a, Combat combat, Player opp) {
        return combatDamage(a, a, combat, opp);
    }

    /** Damage `a` (possibly a pumped copy of `orig`) would deal to the opponent in this combat. */
    private static int combatDamage(Card a, Card orig, Combat combat, Player opp) {
        int unblocked = ComputerUtilCombat.damageIfUnblocked(a, opp, combat, false);
        if (!combat.isBlocked(orig)) {
            return unblocked;
        }
        if (!a.hasKeyword(Keyword.TRAMPLE)) {
            return 0;
        }
        int absorb = 0;
        for (Card b : combat.getBlockers(orig)) {
            absorb += Math.max(0, b.getNetToughness() - b.getDamage());
        }
        return Math.max(0, unblocked - absorb);
    }
}
