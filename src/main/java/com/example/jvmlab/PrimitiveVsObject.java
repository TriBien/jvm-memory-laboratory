package com.example.jvmlab;

import org.openjdk.jol.info.ClassLayout;
import org.openjdk.jol.info.GraphLayout;

public final class PrimitiveVsObject {
    private PrimitiveVsObject() {}

    public static void main(String[] args) {
        int n = args.length > 0 ? Integer.parseInt(args[0]) : 1_000_000;
        if (n < 1) {
            throw new IllegalArgumentException("n must be positive");
        }

        int[] primitives = new int[n];
        Integer[] objects = new Integer[n];

        for (int i = 0; i < n; i++) {
            primitives[i] = i;
            objects[i] = Integer.valueOf(10_000 + i);
        }

        System.out.println("=== VM object layout ===");
        System.out.println(ClassLayout.parseInstance(new Object()).toPrintable());

        System.out.println("=== int[] footprint ===");
        System.out.println(GraphLayout.parseInstance(primitives).toFootprint());

        System.out.println("=== Integer[] graph footprint ===");
        System.out.println(GraphLayout.parseInstance((Object) objects).toFootprint());

        System.out.println("=== Integer element layout ===");
        System.out.println(ClassLayout.parseInstance(objects[n / 2]).toPrintable());
    }
}
