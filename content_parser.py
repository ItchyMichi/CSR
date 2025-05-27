import MeCab


class ContentParser:
    def __init__(self, dic_path=None):
        """
        Initialize the morphological parser.
        If 'dic_path' is provided, it should be the path to a MeCab dictionary.
        Otherwise, MeCab tries to use its default dictionary.
        """
        if dic_path:
            self.tagger = MeCab.Tagger(f"-d {dic_path}")
        else:
            self.tagger = MeCab.Tagger()

    def parse_content(self, content):
        """
        Analyze the given 'content' string and return a list of morpheme dictionaries.

        Returns a list of dicts with keys:
        - 'base_form': The dictionary form of the token
        - 'surface_form': The original surface text
        - 'reading': The reading (kana) of the token, if available
        - 'pos': The part-of-speech string
        """

        # MeCab outputs lines with the format:
        # surface\tfeatures...
        # features are usually comma-separated fields, e.g.:
        # POS1,POS2,POS3,POS4,base_form,reading,pronunciation
        #
        # The last line is 'EOS' which signals the end of parsing.
        #
        # Example line:
        # "食べる\t動詞,自立,*,*,一段,基本形,食べる,タベル,タベル"
        #
        # From this, surface = "食べる"
        # pos might be "動詞"
        # base_form = "食べる"
        # reading = "タベル"

        # Before we parse the content, we need to remove white space and english characters
        # MeCab may not handle these well without a proper dictionary
        content = content.replace(" ", "").replace("　", "")
        content = "".join([c for c in content if not c.isascii()])
        content = content.strip()


        # Parse the content
        node = self.tagger.parseToNode(content)

        results = []
        while node:
            # node.surface gives surface form
            # node.feature gives a CSV string with POS info and other features
            if node.surface:
                features = node.feature.split(",")

                # Depending on the dictionary used, features may vary. For ipadic:
                # features[0] = POS (e.g. "名詞")
                # features[1] = POS category (e.g. "一般")
                # features[6] = base form
                # features[7] = reading (if available)
                # features[8] = pronunciation (if available)

                pos = features[0] if len(features) > 0 else ""
                base_form = features[6] if len(features) > 6 else ""
                reading = features[7] if len(features) > 7 else ""

                # Apply basic filtering:
                # 1. Skip punctuation or symbols often tagged as POS "記号"
                # 2. Skip unknown tokens (base_form == '*')
                # 3. Skip empty surfaces
                if pos != "記号" and base_form != "*" and node.surface.strip() and pos != "助詞":
                    morph = {
                        "base_form": base_form,
                        "surface_form": node.surface,
                        "reading": reading,
                        "pos": pos
                    }
                    results.append(morph)

            node = node.next

        return results

# Example usage:
# parser = MorphManParser()
# sentence = "私は昨日、図書館で本を読みました。"
# morphs = parser.parse_content(sentence)
# for m in morphs:
#     print(m)