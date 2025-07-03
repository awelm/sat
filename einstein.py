from z3 import *

# Create variables that indicate the different possible options.
# For example, when Yellow=3 this means the third house is yellow
Yellow, Blue, Red, Ivory, Green = colors = Ints('Yellow Blue Red Ivory Green')
Norwegian, Ukrainian, Englishman, Spaniard, Japanese = nationalities = Ints('Norwegian Ukrainian Englishman Spaniard Japanese')
Water, Tea, Milk, OrangeJuice, Coffee = beverages = Ints('Water Tea Milk OrangeJuice Coffee')
Kools, Chesterfield, OldGold, LuckyStrike, Parliament = cigarettes = Ints('Kools Chesterfield OldGold LuckyStrike Parliament')
Fox, Horse, Snails, Dog, Zebra = pets = Ints('Fox Horse Snails Dog Zebra')

variables = colors + nationalities + beverages + cigarettes + pets
dimensions = [colors, nationalities, beverages, cigarettes, pets]
s = Solver()

# each house has a different color, nationality, beverage, cigarette, and pet
for dimension in dimensions:
    s.add(Distinct(dimension))

# Constraint 1: There are 5 houses
# Each variable needs to be assigned to one of the 5 houses
for variable in variables:
    s.add(And(variable >= 1, variable <= 5))

s.add(Englishman == Red) # Constraint 2: The Englishman lives in the red house
s.add(Spaniard == Dog) # Constraint 3: The Spaniard owns the dog
s.add(Coffee == Green) # Constraint 4: Coffee is drunk in the green house
s.add(Ukrainian == Tea) # Constraint 5: The Ukrainian drinks tea
s.add(Green == Ivory + 1) # Constraint 6: The green house is immediately to the right of the ivory house
s.add(OldGold == Snails) # And so on...
s.add(Kools == Yellow)
s.add(Milk == 3)
s.add(Norwegian == 1)
s.add(Or(Chesterfield == Fox + 1, Chesterfield == Fox - 1))
s.add(Or(Kools == Horse + 1, Kools == Horse - 1))
s.add(LuckyStrike == OrangeJuice)
s.add(Japanese == Parliament)
s.add(Or(Norwegian == Blue + 1, Norwegian == Blue - 1))

if s.check() == unsat:
    print("Unsatisfiable")
    exit(0)
else:
    m = s.model()
    water_drinker = [nationality for nationality in nationalities if simplify(m[nationality] == m[Water])][0]
    print(f"{water_drinker} drinks water")
    zebra_owner = [nationality for nationality in nationalities if simplify(m[nationality] == m[Zebra])][0]
    print(f"{zebra_owner} owns the zebra")
