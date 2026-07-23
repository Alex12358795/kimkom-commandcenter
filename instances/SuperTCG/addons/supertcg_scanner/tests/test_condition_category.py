from odoo.tests.common import TransactionCase


class TestConditionMapping(TransactionCase):
    """Test condition mapping from Pi payload to internal codes."""

    def test_map_condition_nm_variants(self):
        """Test various NM inputs map to 'nm'."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition('Near Mint'), 'nm')
        self.assertEqual(Card.map_condition('NM'), 'nm')
        self.assertEqual(Card.map_condition('nm'), 'nm')
        self.assertEqual(Card.map_condition('near mint'), 'nm')

    def test_map_condition_ex_variants(self):
        """Test various EX inputs map to 'ex'."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition('Excellent'), 'ex')
        self.assertEqual(Card.map_condition('EX'), 'ex')
        self.assertEqual(Card.map_condition('ex'), 'ex')
        self.assertEqual(Card.map_condition('excellent'), 'ex')

    def test_map_condition_lp_mp_hp(self):
        """Test played condition variants."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition('Lightly Played'), 'lp')
        self.assertEqual(Card.map_condition('LP'), 'lp')
        self.assertEqual(Card.map_condition('Moderately Played'), 'mp')
        self.assertEqual(Card.map_condition('MP'), 'mp')
        self.assertEqual(Card.map_condition('Heavily Played'), 'hp')
        self.assertEqual(Card.map_condition('HP'), 'hp')

    def test_map_condition_pl_po_dmg(self):
        """Test poor/damaged condition variants."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition('Played'), 'pl')
        self.assertEqual(Card.map_condition('PL'), 'pl')
        self.assertEqual(Card.map_condition('Poor'), 'po')
        self.assertEqual(Card.map_condition('PO'), 'po')
        self.assertEqual(Card.map_condition('Damaged'), 'dmg')
        self.assertEqual(Card.map_condition('DMG'), 'dmg')

    def test_map_condition_empty(self):
        """Test empty condition defaults to 'ex'."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition(''), 'ex')
        self.assertEqual(Card.map_condition(None), 'ex')
        self.assertEqual(Card.map_condition(False), 'ex')

    def test_map_condition_unknown(self):
        """Test unknown condition defaults to 'ex'."""
        Card = self.env['supertcg.batch.card']
        self.assertEqual(Card.map_condition('SomeRandomCondition'), 'ex')


class TestCardCategoryDetection(TransactionCase):
    """Test auto-detection of card category from Pi payload fields."""

    def test_detect_reverse_holo(self):
        """Test reverse holo detection."""
        Card = self.env['supertcg.batch.card']
        data = {'is_reverse_holo': 'true'}
        self.assertEqual(Card.detect_card_category(data), 'reverse_holo')

    def test_detect_holo(self):
        """Test holo detection from foil + printing."""
        Card = self.env['supertcg.batch.card']
        data = {'foil': 'true', 'printing': 'Holofoil'}
        self.assertEqual(Card.detect_card_category(data), 'holo')

    def test_detect_common(self):
        """Test common rarity detection."""
        Card = self.env['supertcg.batch.card']
        data = {'rarity': 'Common'}
        self.assertEqual(Card.detect_card_category(data), 'common')

    def test_detect_uncommon(self):
        """Test uncommon rarity detection."""
        Card = self.env['supertcg.batch.card']
        data = {'rarity': 'Uncommon'}
        self.assertEqual(Card.detect_card_category(data), 'uncommon')

    def test_detect_vmax(self):
        """Test VMAX detection from card name."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Charizard VMAX'}
        self.assertEqual(Card.detect_card_category(data), 'vmax')

    def test_detect_v(self):
        """Test V detection from card name."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Pikachu V'}
        self.assertEqual(Card.detect_card_category(data), 'v')

    def test_detect_ex(self):
        """Test EX detection from card name."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Mewtwo EX'}
        self.assertEqual(Card.detect_card_category(data), 'ex')

    def test_detect_full_art(self):
        """Test Full Art detection."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Charizard Full Art'}
        self.assertEqual(Card.detect_card_category(data), 'full_art')

    def test_detect_alternate_art(self):
        """Test Alternate Art detection."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Pikachu Alternate Art'}
        self.assertEqual(Card.detect_card_category(data), 'alternate_art')

    def test_detect_secret_rare(self):
        """Test Secret Rare detection."""
        Card = self.env['supertcg.batch.card']
        data = {'rarity': 'Secret Rare'}
        self.assertEqual(Card.detect_card_category(data), 'secret_rare')

    def test_detect_default_other(self):
        """Test default category is 'other'."""
        Card = self.env['supertcg.batch.card']
        data = {'card_name': 'Random Card'}
        self.assertEqual(Card.detect_card_category(data), 'other')

    def test_detect_vmax_in_rarity(self):
        """Test VMAX can be detected from rarity field too."""
        Card = self.env['supertcg.batch.card']
        data = {'rarity': 'VMAX Rare'}
        self.assertEqual(Card.detect_card_category(data), 'vmax')

    def test_detect_priority_reverse_over_holo(self):
        """Test reverse holo takes priority over holo."""
        Card = self.env['supertcg.batch.card']
        data = {'is_reverse_holo': 'true', 'foil': 'true', 'printing': 'Holofoil'}
        self.assertEqual(Card.detect_card_category(data), 'reverse_holo')
