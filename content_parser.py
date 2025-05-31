from sudachipy import tokenizer
from sudachipy import dictionary


class ContentParser:
    def __init__(self):
        # Initialize Sudachi tokenizer
        self.tokenizer_obj = dictionary.Dictionary().create()
        self.mode = tokenizer.Tokenizer.SplitMode.C

    def katakana_to_hiragana(self, text):
        """
        Convert Katakana characters to Hiragana.
        """
        return ''.join(
            chr(ord(c) - ord('ァ') + ord('ぁ')) if 'ァ' <= c <= 'ン' else c
            for c in text
        )

    def parse_content(self, content):
        """
        Analyze 'content' string and return list of morpheme dictionaries.

        Each dictionary contains:
        - 'base_form': Lemma form
        - 'surface_form': Original text
        - 'reading': Kana reading (in hiragana)
        - 'pos': Part-of-speech
        """

        # Remove spaces and ASCII characters for clean parsing
        content = content.replace(" ", "").replace("　", "")
        content = "".join([c for c in content if not c.isascii()])
        content = content.strip()

        tokens = self.tokenizer_obj.tokenize(content, self.mode)

        results = []
        for m in tokens:
            pos = m.part_of_speech()[0]
            base_form = m.dictionary_form()
            surface_form = m.surface()
            reading_katakana = m.reading_form()
            reading_hiragana = self.katakana_to_hiragana(reading_katakana)

            # Basic filtering similar to original MeCab logic
            if pos != "記号" and pos != "補助記号" and base_form != "" and surface_form.strip():

                morph = {
                    "base_form": base_form,
                    "surface_form": surface_form,
                    "reading": reading_hiragana,
                    "pos": pos
                }
                results.append(morph)

        return results


# Test cases with varying complexity
if __name__ == "__main__":
    parser = ContentParser()

    test_sentences = [
        "怪獣が現れて、先輩が逃げろって、あの時、助けてくれなかったら、俺は今日、死んでました。",
        "やっぱなるべきっすよ。",
        "防衛隊員。",
        "ありがとな、イチコ。",
        "お前、やっぱいい奴だわ。俺、もう一回防衛隊員目指す。",
        "見つけた。",
        "一分後に、戻ってきた。",
        "あなたはまた戻ってきた。最初に、戻ってきた。",
        "それが白の赤の赤の赤の辿り道で、それも同じか。",
        "お前はどこにあるの？",
        "結構長い時間とても厳しいです。",
        "私はこれが帰りたいです。",
        "私はこれらの物語を別の言葉ではありませんでした。",
        "自分の中で何をしていたのか疑問なことを知ることがあります。",
        "怪獣は必ず倒す。",
        "大の怪獣が発生しました。",
        "横浜市に小型の怪獣が発生しました。",
        "音変えろよ、久美。翔ちゃん、早く！",
        "市民の皆さんは、速やかにシェルターに避難する。",
        "命を守る行動をとってください。",
        "誤解を解かないと！",
        "先輩、笑顔！",
        "ああ、これ絶対ダメな奴だ。やっぱり！",
        "おい、じいさん、大丈夫か？",
        "これじゃマジで怪獣じゃん！",
        "爆発か？",
        "もう防衛隊が来ます！",
        "逃げましょう！",
        "このままじゃ病院に迷惑かけちまうしな！",
        "窓から行こう！",
        "逃げますよ、先輩！",
        "一体どうなってるんだ？",
        "先輩が怪獣？",
        "いつから？",
        "ていうか、怪獣なのか我は？",
        "本当に先輩なんですよね？",
        "自分でも分からんくなってきた！",
        "何者だ！",
        "むしろ俺が知りたい！",
        "めっちゃきもいっせ先輩！",
        "戻り方もきも！",
        "すっげえおしっこしたい。",
        "我慢してください！",
        "人として大人として、合同でおしっこしたくない！",
        "いや、他にもっと気にするとこあるでしょ！",
        "俺これからどうなっちゃうのかな？",
        "無理無理無理無理無理無理無理！",
        "どう見ても討伐される側、即殺処分っす！",
        "ってことは、もう俺が隊員になることってないのか？",
        "こんな体でどうやって？",
        "何か来る！",
        "隊員！？",
        "別の怪獣？",
        "2号車はこのまま直進。",
        "俺たちを襲ったのと同時だな。",
        "これで先輩に裂かれる隊員の数が減る。",
        "身を隠すチャンスです。",
        "被害者がいないことを祈りましょう。",
        "すっげぇ威力。大丈夫？",
        "わ、わかった！",
        "すぐいなくなるから泣かないで！",
        "気絶してるだけだ。大丈夫？",
        "石川、2人を頼む。どうするんです！",
    ]

    for idx, sentence in enumerate(test_sentences, 1):
        print(f"\nTest {idx}: {sentence}")
        morphs = parser.parse_content(sentence)
        for m in morphs:
            print(m)
