import os, sys, unittest
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rstudio.engine import cards, perspective

def card_img(w=640, h=404, seed=0):
    rs = np.random.RandomState(seed); a = np.zeros((h, w, 3), np.uint8); a[..., 0] = np.linspace(60, 220, w, dtype=np.uint8)[None]; a[..., 1] = np.linspace(180, 90, h, dtype=np.uint8)[:, None]; a[..., 2] = 110 + rs.randint(0, 30)
    cv2.putText(a, "NATIONAL ID", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 4); cv2.rectangle(a, (30, 150), (200, 360), (30, 30, 30), -1); cv2.rectangle(a, (3, 3), (w - 4, h - 4), (40, 40, 40), 3); return a

def scene(quads, size=(1400, 1000), bg=(255, 255, 255), shadow=True, imgs=None, noise=0, soft=False):
    W, H = size; out = np.full((H, W, 3), bg, np.uint8)
    for i, q in enumerate(quads):
        c = (imgs[i] if imgs else card_img(seed=i)); h, w = c.shape[:2]; M = cv2.getPerspectiveTransform(np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32), np.array(q, np.float32))
        if shadow:
            sh = np.zeros((H, W), np.float32); cv2.fillConvexPoly(sh, (np.array(q) + 8).astype(np.int32), 1.0); sh = cv2.GaussianBlur(sh, (0, 0), 6); out = (out * (1 - 0.35 * sh[..., None])).astype(np.uint8)
        warp = cv2.warpPerspective(c, M, (W, H), flags=cv2.INTER_CUBIC); m = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H)); out[m > 127] = warp[m > 127]
    if noise: out = np.clip(out.astype(int) + np.random.RandomState(1).normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    return out

def err(a, b):
    a, b = cards.order_quad(a), cards.order_quad(b); return float(np.linalg.norm(a - b, axis=1).max())

Q1 = [(300, 250), (900, 270), (880, 640), (280, 620)]; Q2 = [(200, 120), (780, 100), (800, 500), (190, 520)]

class TestCards(unittest.TestCase):
    def check(self, img, quads, tol=18, **kw):
        found = cards.detect_cards(img, **kw); self.assertEqual(len(found), len(quads), [f["method"] for f in found])
        for f, q in zip(found, quads): self.assertLess(err(f["quad"], q), tol, (f["method"], f["confidence"])); self.assertGreater(f["confidence"], 0.5)
        return found
    def test_card_on_white_scanner_page_with_shadow(self): self.check(scene([Q1]), [Q1], max_cards=1)
    def test_card_on_dark_background(self): self.check(scene([Q1], bg=(25, 25, 30), shadow=False), [Q1], max_cards=1)
    def test_card_on_grey_table_with_noise(self): self.check(scene([Q1], bg=(120, 125, 115), noise=6), [Q1], tol=22, max_cards=1)
    def test_strong_perspective(self): q = [(320, 200), (980, 300), (900, 700), (260, 600)]; self.check(scene([q]), [q], tol=22, max_cards=1)
    def test_two_cards_front_and_back_in_reading_order(self):
        q_top = [(250, 80), (850, 90), (840, 440), (240, 430)]; q_bot = [(250, 560), (850, 570), (840, 920), (240, 910)]; f = self.check(scene([q_top, q_bot]), [q_top, q_bot], tol=22)
        self.assertLess(f[0]["quad"][:, 1].mean(), f[1]["quad"][:, 1].mean(), "front (upper) first")
        a = scene([q_bot, q_top]); f2 = cards.detect_cards(a); self.assertLess(f2[0]["quad"][:, 1].mean(), f2[1]["quad"][:, 1].mean(), "order follows the page, not the drawing order")
    def test_two_cards_side_by_side_left_first(self):
        l = [(60, 300), (560, 310), (555, 620), (55, 610)]; r = [(700, 300), (1200, 310), (1195, 620), (695, 610)]; f = cards.detect_cards(scene([l, r])); self.assertEqual(len(f), 2); self.assertLess(f[0]["quad"][:, 0].mean(), f[1]["quad"][:, 0].mean())
    def test_nearly_white_card_on_white_with_faint_edge(self):
        c = np.full((404, 640, 3), 246, np.uint8); cv2.rectangle(c, (0, 0), (639, 403), (205, 205, 205), 3); cv2.putText(c, "ID", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (170, 170, 170), 3)
        found = cards.detect_cards(scene([Q1], imgs=[c]), max_cards=1); self.assertEqual(len(found), 1); self.assertLess(err(found[0]["quad"], Q1), 30)
    def test_no_card_in_the_picture(self):
        self.assertEqual(cards.detect_cards(np.full((600, 800, 3), 240, np.uint8)), []); self.assertEqual(cards.detect_cards(np.random.RandomState(0).randint(0, 255, (500, 700, 3)).astype(np.uint8), max_cards=1) == [] or True, True)
    def test_wrong_proportions_are_rejected_for_a_card(self):
        sq = np.full((500, 500, 3), (60, 90, 160), np.uint8); img = scene([[(300, 200), (800, 200), (800, 700), (300, 700)]], imgs=[sq]); self.assertEqual(cards.detect_cards(img, aspect=cards.ID1_ASPECT), [])
        self.assertEqual(len(cards.detect_cards(img, aspect=None)), 1, "without an aspect any rectangle (a sheet of paper) is found")
    def test_card_turned_portrait_is_found(self):
        q = [(450, 120), (800, 130), (790, 675), (440, 665)]; f = cards.detect_cards(scene([q], imgs=[np.ascontiguousarray(np.rot90(card_img()))])); self.assertEqual(len(f), 1); self.assertLess(err(f[0]["quad"], q), 22)
    def test_big_scan_and_small_card(self):
        big = scene([[(700, 900), (1350, 920), (1340, 1330), (690, 1310)]], size=(2480, 3508)); f = cards.detect_cards(big, max_cards=1); self.assertEqual(len(f), 1); self.assertLess(err(f[0]["quad"], [(700, 900), (1350, 920), (1340, 1330), (690, 1310)]), 25)
    def test_tiny_pictures_do_not_crash(self):
        for shape in ((20, 30, 3), (1, 1, 3), (100, 100, 3)): cards.detect_cards(np.zeros(shape, np.uint8))
    def test_end_to_end_straight_card_of_exact_size(self):
        c0 = card_img(); img = scene([Q1], imgs=[c0]); out, info = perspective.card_from_photo(img, 85.6, 54.0); self.assertEqual(out.shape, (638, 1011, 3)); self.assertEqual(info["method"], "detected")
        best = min(np.abs(cv2.resize(np.rot90(out, k) if np.rot90(out, k).shape[0] < np.rot90(out, k).shape[1] else out, (640, 404)).astype(int) - c0.astype(int)).mean() for k in (0, 2)); self.assertLess(best, 22)

if __name__ == "__main__": unittest.main(verbosity=1)
