import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;


public class TreePerm {
	public static void main(String[] args) throws IOException {
		long seed = Long.parseLong(args[0]);
		final BufferedReader r = new BufferedReader(new InputStreamReader(System.in));
		StringBuilder sb = new StringBuilder();
		while(r.ready()) {
			sb.append(r.readLine() + "\n");
		}
		String svgFile = sb.toString();
		final String charset = "ABCDEFGHKLMNOPQRSTUVWXYZ";
		final Random rng = new Random(seed);
		final List<Character> cs = new ArrayList<>();
		for (final char c : charset.toCharArray()) {
			cs.add(c);
		}
		Collections.shuffle(cs, rng);
		final List<Character> charsToUse = cs.subList(0, 9);
		Collections.sort(charsToUse);
		for(int i = charsToUse.size(); i > 0; i--) {
			svgFile = svgFile.replaceAll("##" + i, Character.toString(charsToUse.get(i - 1)));
		}
		System.out.println(svgFile);
	}
}
