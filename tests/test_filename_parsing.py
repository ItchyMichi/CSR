import unittest
from file_utils import parse_filename_for_show_episode

class TestFilenameParsing(unittest.TestCase):
    def test_subsplease(self):
        title, season, episode = parse_filename_for_show_episode("[SubsPlease] Kaijuu 8-gou - 01 (480p) [E7479F2F]")
        self.assertEqual(title, "kaijuu 8 gou")
        self.assertIsNone(season)
        self.assertEqual(episode, 1)

    def test_judas(self):
        title, season, episode = parse_filename_for_show_episode("[Judas] Digimon Adventure - S01E01")
        self.assertEqual(title, "digimon adventure")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 1)

    def test_coalgirls(self):
        title, season, episode = parse_filename_for_show_episode("[Coalgirls]_My_Neighbor_Totoro_(1280x692_Blu-ray_FLAC)_[949BDC65]")
        self.assertEqual(title, "my neighbor totoro")
        self.assertIsNone(season)
        self.assertIsNone(episode)

if __name__ == '__main__':
    unittest.main()
